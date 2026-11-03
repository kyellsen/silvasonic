"""BirdNET — Wikipedia Species Data Enricher.

Fetches bird species data (summary text + images) from the Wikipedia
REST API and caches them locally (DB + workspace filesystem).

Both EN and DE summaries are always fetched and stored to support
instant language switching via the UI settings.

Storage follows the Two-Worlds architecture (ADR-0005):
- World A (container image): Immutable code, static assets
- World B (workspace bind mount): Mutable runtime data (cached images)

Images are stored under ``birdnet/wiki/img/`` in the workspace
(ADR-0008: Domain-Driven Workspace Isolation).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
from silvasonic.core.database.models.taxonomy import Taxonomy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Wikipedia REST API base URL pattern
_WIKI_API = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"

# User-Agent per Wikimedia policy
_USER_AGENT = (
    "Silvasonic/1.0 (https://github.com/kyellsen/silvasonic; bioacoustic monitoring)"
)

# Cached bird images directory relative to workspace root
# Full path: /data/birdnet/wiki/img/
_WIKI_IMG_DIR = Path("wiki/img")

# Default thumbnail width to download (good balance: card + hero banner)
_THUMB_WIDTH = 800

# Rate limiting: minimum seconds between Wikipedia API calls
_MIN_REQUEST_INTERVAL_S = 0.5


@dataclass
class WikiEnrichmentResult:
    """Typed result from a Wikipedia enrichment operation."""

    description: dict[str, str] = field(default_factory=dict)
    image_url: str | None = None
    image_source: str | None = None
    wiki_urls: dict[str, str | None] = field(
        default_factory=lambda: {"en": None, "de": None}
    )


def _slug(scientific_name: str) -> str:
    """Convert scientific name to filesystem-safe slug.

    Example: 'Turdus merula' -> 'turdus_merula'
    """
    return re.sub(r"[^a-z0-9]+", "_", scientific_name.lower()).strip("_")


def _make_thumb_url(original_url: str, width: int = _THUMB_WIDTH) -> str | None:
    """Convert a Wikimedia original image URL to a resized thumbnail URL.

    Wikimedia thumb URL pattern:
        .../commons/thumb/{hash}/{filename}/{width}px-{filename}

    Example:
        Input:  https://upload.wikimedia.org/wikipedia/commons/a/a9/Common_Blackbird.jpg
        Output: https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Common_Blackbird.jpg/800px-Common_Blackbird.jpg
    """
    if not original_url or "upload.wikimedia.org" not in original_url:
        return None

    # Already a thumb URL — just replace width
    if "/thumb/" in original_url:
        parts = original_url.rsplit("/", 1)
        if len(parts) == 2:
            filename = parts[0].rsplit("/", 1)[-1]
            return f"{parts[0]}/{width}px-{filename}"
        return None

    # Original URL → construct thumb URL
    original_url = original_url.replace("/commons/", "/commons/thumb/", 1)
    filename = original_url.rsplit("/", 1)[-1]
    return f"{original_url}/{width}px-{filename}"


async def fetch_wiki_summary(
    scientific_name: str, lang: str
) -> dict[str, Any] | None:
    """Fetch a Wikipedia page summary for a species.

    Args:
        scientific_name: Scientific species name (e.g. 'Turdus merula')
        lang: Wikipedia language code ('en' or 'de')

    Returns:
        Dict with keys: extract_html, extract, thumbnail_url, original_image_url,
        wiki_page_url, short_description. Or None on failure.
    """
    title = scientific_name.replace(" ", "_")
    url = _WIKI_API.format(lang=lang, title=title)

    retries = 3
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
                timeout=15.0,
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 429:
                    # Rate limited — back off
                    wait = 2.0 * (attempt + 1)
                    log.warning(
                        "wiki_rate_limited",
                        species=scientific_name,
                        lang=lang,
                        retry_in=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    log.warning(
                        "wiki_fetch_failed",
                        species=scientific_name,
                        lang=lang,
                        status=resp.status_code,
                    )
                    return None

                data = resp.json()

                return {
                    "extract_html": data.get("extract_html", ""),
                    "extract": data.get("extract", ""),
                    "thumbnail_url": (data.get("thumbnail") or {}).get("source"),
                    "original_image_url": (data.get("originalimage") or {}).get(
                        "source"
                    ),
                    "wiki_page_url": (
                        data.get("content_urls", {}).get("desktop") or {}
                    ).get("page"),
                    "short_description": data.get("description", ""),
                }

        except Exception:
            log.exception(
                "wiki_fetch_error",
                species=scientific_name,
                lang=lang,
                attempt=attempt + 1,
            )
            if attempt < retries - 1:
                await asyncio.sleep(1.0)

    return None


async def _download_image(url: str, dest_path: Path) -> bool:
    """Download an image from Wikimedia and save to disk.

    Args:
        url: Image URL (should be a Wikimedia thumb URL)
        dest_path: Absolute path to save the image (in workspace)

    Returns:
        True if download succeeded.
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                log.warning(
                    "image_download_failed", url=url, status=resp.status_code
                )
                return False

            dest_path.write_bytes(resp.content)
            log.info(
                "image_downloaded",
                url=url,
                dest=str(dest_path),
                size_kb=len(resp.content) // 1024,
            )
            return True

    except Exception:
        log.exception("image_download_error", url=url)
        return False


async def enrich_if_needed(
    label: str,
    session: AsyncSession,
    workspace_dir: Path,
    *,
    worker: str = "birdnet",
    force: bool = False,
) -> WikiEnrichmentResult:
    """Fetch Wikipedia data for a species if not already cached.

    This is the main entry point. It:
    1. Checks if data is already cached in the Taxonomy table
    2. If not (or force=True), fetches EN + DE summaries in parallel
    3. Downloads the species image (800px JPEG) to workspace
    4. Updates the Taxonomy row with description + image_path + image_source
    5. Returns a typed result

    Images are stored in the workspace (World B / ADR-0005) under
    ``wiki/img/`` (ADR-0008: Domain-Driven Workspace Isolation).

    Args:
        label: Full detection label (e.g. 'Turdus merula_Eurasian Blackbird')
        session: SQLAlchemy async session
        workspace_dir: Absolute path to the birdnet workspace (/data/birdnet)
        worker: Worker key for Taxonomy lookup (default: 'birdnet')
        force: If True, re-fetch even if cached

    Returns:
        WikiEnrichmentResult with description, image_url, image_source, wiki_urls
    """
    result = WikiEnrichmentResult()

    # Parse label: "Turdus merula_Eurasian Blackbird" → scientific_name
    scientific_name = label.split("_", 1)[0].strip() if "_" in label else label

    # 1. Check existing Taxonomy record
    stmt = select(Taxonomy).where(
        Taxonomy.worker == worker,
        Taxonomy.label == label,
    )
    taxonomy = (await session.execute(stmt)).scalars().first()

    if taxonomy and not force:
        desc = taxonomy.description if isinstance(taxonomy.description, dict) else {}
        has_description = bool(desc.get("en") or desc.get("de"))
        has_image = bool(taxonomy.image_path)

        if has_description and has_image:
            # Fully cached — verify image still exists on disk
            image_file = workspace_dir / _WIKI_IMG_DIR / Path(taxonomy.image_path).name
            result.description = desc
            result.image_url = (
                f"/media/birdnet-wiki/img/{Path(taxonomy.image_path).name}"
                if image_file.exists()
                else None
            )
            result.image_source = taxonomy.image_source
            result.wiki_urls = {
                "en": f"https://en.wikipedia.org/wiki/{scientific_name.replace(' ', '_')}",
                "de": f"https://de.wikipedia.org/wiki/{scientific_name.replace(' ', '_')}",
            }
            log.debug("wiki_cache_hit", species=scientific_name)
            return result

    # 2. Fetch EN + DE in parallel
    log.info("wiki_fetching", species=scientific_name)
    en_data, de_data = await asyncio.gather(
        fetch_wiki_summary(scientific_name, "en"),
        fetch_wiki_summary(scientific_name, "de"),
    )

    # Rate limiting between API calls
    await asyncio.sleep(_MIN_REQUEST_INTERVAL_S)

    # 3. Build description JSONB
    description: dict[str, str] = {}
    if en_data and en_data["extract_html"]:
        description["en"] = en_data["extract_html"]
    if de_data and de_data["extract_html"]:
        description["de"] = de_data["extract_html"]

    result.description = description

    # 4. Download image to workspace
    source_data = en_data or de_data
    image_filename: str | None = None
    image_source: str | None = None

    if source_data:
        original_url = source_data.get("original_image_url")
        thumb_url = source_data.get("thumbnail_url")

        if original_url:
            image_source = original_url
            result.image_source = original_url

            # Create 800px thumb URL from original
            download_url = _make_thumb_url(original_url, _THUMB_WIDTH)
            if not download_url and thumb_url:
                download_url = thumb_url  # Fallback to API thumbnail

            if download_url:
                slug = _slug(scientific_name)
                # Determine extension from URL
                ext = ".jpg"
                if ".png" in download_url.lower():
                    ext = ".png"
                elif ".svg" in download_url.lower():
                    ext = ".svg"

                image_filename = f"{slug}{ext}"
                dest = workspace_dir / _WIKI_IMG_DIR / image_filename

                if not dest.exists() or force:
                    success = await _download_image(download_url, dest)
                    if not success:
                        image_filename = None
                        log.warning("wiki_image_failed", species=scientific_name)

        # Wiki page URLs
        if en_data and en_data.get("wiki_page_url"):
            result.wiki_urls["en"] = en_data["wiki_page_url"]
        if de_data and de_data.get("wiki_page_url"):
            result.wiki_urls["de"] = de_data["wiki_page_url"]

    # 5. Update Taxonomy record in DB
    if taxonomy:
        if description:
            taxonomy.description = description
        if image_filename:
            taxonomy.image_path = image_filename
        if image_source:
            taxonomy.image_source = image_source
        await session.commit()
        log.info("wiki_taxonomy_updated", species=scientific_name)
    else:
        log.warning(
            "wiki_no_taxonomy_record",
            species=scientific_name,
            worker=worker,
            msg="Taxonomy record not found — cannot cache wiki data.",
        )

    if image_filename:
        result.image_url = f"/media/birdnet-wiki/img/{image_filename}"

    return result
