"""BirdNET — Wikipedia species enrichment.

Fetches a description and a picture of a species from Wikipedia and stores
them on its ``species`` row and in the workspace, so that the station can
show them without internet access later.  English and German texts are both
fetched, so the interface can switch language instantly.

Three rules shape this module:

*   **No network call inside a database transaction.**  The station database
    is SQLite: every transaction holds the write lock (ADR-0037).  A lookup
    reads the row in one short transaction, talks to Wikipedia with none
    open, and writes the result in a second short one.
*   **Only what can be attributed is kept.**  Wikipedia text is licensed
    CC BY-SA 4.0: its source article and licence are stored per language.
    A picture is taken only from Wikimedia Commons, whose files are all under
    free licences; author, licence and file page are read from the Commons
    API and stored with it.  A picture without that information is not kept.
    Pictures from a language Wikipedia's own uploads (often non-free, used
    there under fair use) are never taken.
*   **Text, never HTML.**  Descriptions are stored as plain text, so nothing
    from outside can carry markup or script into the interface.

Storage follows the Two-Worlds architecture (ADR-0005): pictures are runtime
data under ``wiki/img/`` in the BirdNET workspace (ADR-0008), named after the
species id.

Enrichment is best effort.  It needs the ``species`` row that BirdNET
registers with the first detection of a label (``silvasonic.birdnet.species``),
skips sound classes that are not species, and asks Wikipedia about one species
at most once per ``_RETRY_INTERVAL_S`` until the row is complete.
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import structlog
from silvasonic.birdnet.species import ANALYZER, split_label
from silvasonic.core.database.models.species import Species
from silvasonic.core.database.session import get_session
from sqlalchemy import select, update

log = structlog.get_logger()

# Wikipedia REST API: summary of an article
_WIKI_API = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
# Wikimedia Commons API: author and licence of a file
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Original files on Commons; a language Wikipedia's own uploads live elsewhere
_COMMONS_UPLOAD = "upload.wikimedia.org/wikipedia/commons/"

# Licence of all Wikipedia article text
TEXT_LICENSE = "CC BY-SA 4.0"
TEXT_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

# User-Agent per Wikimedia policy
_USER_AGENT = "Silvasonic/1.0 (https://github.com/kyellsen/silvasonic; bioacoustic monitoring)"

# Cached species images, relative to the BirdNET workspace root.
# ``species.image_path`` holds this directory plus the file name.
_WIKI_IMG_DIR = Path("wiki/img")

# Default thumbnail width to download (good balance: card + hero banner)
_THUMB_WIDTH = 800

# Rate limiting: minimum seconds between Wikipedia API calls
_MIN_REQUEST_INTERVAL_S = 0.5

# A species whose lookup failed or stayed incomplete (no article, no picture,
# station offline) is not looked up again before this much time has passed.
_RETRY_INTERVAL_S = 6 * 3600.0

# species id -> monotonic time of the earliest next lookup (per process)
_next_attempt: dict[str, float] = {}

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass
class ImageAttribution:
    """What a picture's licence asks to be shown with it."""

    author: str
    license: str
    license_url: str | None
    page_url: str


@dataclass
class WikiEnrichmentResult:
    """Typed result from a Wikipedia enrichment operation."""

    descriptions: dict[str, str] = field(default_factory=dict)
    description_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    # Relative to the BirdNET workspace; None if there is no picture on disk
    image_path: str | None = None
    image_source: str | None = None
    image_author: str | None = None
    image_license: str | None = None
    image_license_url: str | None = None
    wiki_urls: dict[str, str | None] = field(default_factory=lambda: {"en": None, "de": None})


def plain_text(markup: str) -> str:
    """Reduce HTML to plain text: tags removed, entities decoded, spaces collapsed."""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", markup))).strip()


def _is_commons(url: str | None) -> bool:
    return bool(url) and _COMMONS_UPLOAD in str(url)


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


def _commons_file_name(url: str) -> str:
    """``File:…`` title of a Commons upload or thumbnail URL."""
    path = url.split(_COMMONS_UPLOAD, 1)[1]
    parts = path.split("/")
    # thumb/a/a9/Name.jpg/800px-Name.jpg  or  a/a9/Name.jpg
    name = parts[3] if parts[0] == "thumb" else parts[2]
    return "File:" + unquote(name)


async def fetch_wiki_summary(scientific_name: str, lang: str) -> dict[str, Any] | None:
    """Fetch a Wikipedia page summary for a species.

    Args:
        scientific_name: Scientific species name (e.g. 'Turdus merula')
        lang: Wikipedia language code ('en' or 'de')

    Returns:
        Dict with keys: extract (plain text), thumbnail_url, original_image_url,
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
                    "extract": plain_text(data.get("extract", "")),
                    "thumbnail_url": (data.get("thumbnail") or {}).get("source"),
                    "original_image_url": (data.get("originalimage") or {}).get("source"),
                    "wiki_page_url": (data.get("content_urls", {}).get("desktop") or {}).get(
                        "page"
                    ),
                    "short_description": plain_text(data.get("description", "")),
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


async def fetch_commons_attribution(image_url: str) -> ImageAttribution | None:
    """Read author, licence and file page of a Commons file.

    Returns ``None`` for a file not on Commons, on failure, or when Commons
    names no licence: such a picture cannot be shown with its attribution.
    """
    if not _is_commons(image_url):
        return None
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "extmetadata|url",
        "titles": _commons_file_name(image_url),
    }
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=15.0,
        ) as client:
            resp = await client.get(_COMMONS_API, params=params)
        if resp.status_code != 200:
            log.warning("commons_metadata_failed", url=image_url, status=resp.status_code)
            return None
        pages = resp.json().get("query", {}).get("pages", {})
        info = next(iter(pages.values()), {}).get("imageinfo", [{}])[0]
    except Exception:
        log.exception("commons_metadata_error", url=image_url)
        return None

    meta = info.get("extmetadata", {})

    def value(key: str) -> str:
        return plain_text(str((meta.get(key) or {}).get("value", "")))

    license_name = value("LicenseShortName")
    page_url = info.get("descriptionurl")
    if not license_name or not page_url:
        log.warning("commons_license_unknown", url=image_url)
        return None
    return ImageAttribution(
        author=value("Artist") or value("Credit") or "Unknown",
        license=license_name,
        license_url=value("LicenseUrl") or None,
        page_url=str(page_url),
    )


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
                log.warning("image_download_failed", url=url, status=resp.status_code)
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


def _cached(species: Species, workspace_dir: Path, scientific_name: str) -> WikiEnrichmentResult:
    """Build a result from what the ``species`` row and the workspace already hold."""
    descriptions = species.descriptions if isinstance(species.descriptions, dict) else {}
    sources = species.description_sources if isinstance(species.description_sources, dict) else {}
    on_disk = bool(species.image_path) and (workspace_dir / str(species.image_path)).exists()
    title = scientific_name.replace(" ", "_")
    return WikiEnrichmentResult(
        descriptions=dict(descriptions),
        description_sources=dict(sources),
        image_path=species.image_path if on_disk else None,
        image_source=species.image_source,
        image_author=species.image_author,
        image_license=species.image_license,
        image_license_url=species.image_license_url,
        wiki_urls={
            "en": f"https://en.wikipedia.org/wiki/{title}",
            "de": f"https://de.wikipedia.org/wiki/{title}",
        },
    )


async def _fetch_picture(
    source_data: dict[str, Any], species_id: str, workspace_dir: Path, force: bool
) -> tuple[str, ImageAttribution] | None:
    """Download the article's picture if Commons can attribute it; return path and attribution."""
    original_url = source_data.get("original_image_url")
    if not _is_commons(original_url):
        if original_url:
            log.info("wiki_image_not_on_commons", url=original_url)
        return None
    attribution = await fetch_commons_attribution(str(original_url))
    if attribution is None:
        return None

    download_url = _make_thumb_url(str(original_url), _THUMB_WIDTH)
    thumb_url = source_data.get("thumbnail_url")
    if not download_url and _is_commons(thumb_url):
        download_url = str(thumb_url)  # Fallback to API thumbnail
    if not download_url:
        return None

    ext = ".jpg"
    if ".png" in download_url.lower():
        ext = ".png"
    elif ".svg" in download_url.lower():
        ext = ".svg"
    image_path = str(_WIKI_IMG_DIR / f"{species_id}{ext}")
    dest = workspace_dir / image_path
    if (not dest.exists() or force) and not await _download_image(download_url, dest):
        log.warning("wiki_image_failed", species=species_id)
        return None
    return image_path, attribution


async def enrich_if_needed(
    label: str,
    workspace_dir: Path,
    *,
    analyzer: str = ANALYZER,
    force: bool = False,
) -> WikiEnrichmentResult:
    """Fetch Wikipedia data for a species if not already cached.

    This is the main entry point. It:
    1. Reads the ``species`` row of the label in a short transaction; without
       one there is nothing to enrich
    2. Returns what is cached if the row is complete, is a sound class that
       is not a species, or was looked up recently
    3. Otherwise (or with force=True), with no transaction open: fetches the
       EN and DE summaries, reads the picture's attribution from Commons and
       downloads it (800 px) to the workspace
    4. Writes descriptions, their sources and the picture with its
       attribution in a second short transaction

    Args:
        label: Full detection label (e.g. 'Turdus merula_Eurasian Blackbird')
        workspace_dir: Absolute path to the birdnet workspace (/data/birdnet)
        analyzer: Analyzer the label belongs to (default: 'birdnet')
        force: If True, re-fetch even if cached, skipped or looked up recently

    Returns:
        WikiEnrichmentResult with what the row now holds.
    """
    # Parse label: "Turdus merula_Eurasian Blackbird" → scientific_name
    scientific_name = split_label(label)[0].strip()

    # 1. Read the species row; the session closes before any network call
    async with get_session() as session:
        species = (
            (
                await session.execute(
                    select(Species).where(Species.analyzer == analyzer, Species.label == label)
                )
            )
            .scalars()
            .first()
        )

    if species is None:
        log.warning("wiki_no_species_record", label=label, analyzer=analyzer)
        return WikiEnrichmentResult()

    result = _cached(species, workspace_dir, scientific_name)

    if not force:
        if species.category == "other":
            # A sound class such as an engine or speech: no article describes it
            return result

        has_description = bool(result.descriptions.get("en") or result.descriptions.get("de"))
        if has_description and result.image_path:
            log.debug("wiki_cache_hit", species=scientific_name)
            return result

        if time.monotonic() < _next_attempt.get(species.id, 0.0):
            return result

    _next_attempt[species.id] = time.monotonic() + _RETRY_INTERVAL_S

    # 2. Network, with no database transaction open
    log.info("wiki_fetching", species=scientific_name)
    by_lang = dict(
        zip(
            ("en", "de"),
            await asyncio.gather(
                fetch_wiki_summary(scientific_name, "en"),
                fetch_wiki_summary(scientific_name, "de"),
            ),
            strict=True,
        )
    )
    await asyncio.sleep(_MIN_REQUEST_INTERVAL_S)  # be polite to the API

    descriptions: dict[str, str] = {}
    sources: dict[str, dict[str, str]] = {}
    for lang, data in by_lang.items():
        if not data:
            continue
        if data.get("wiki_page_url"):
            result.wiki_urls[lang] = data["wiki_page_url"]
        if data.get("extract") and data.get("wiki_page_url"):
            descriptions[lang] = data["extract"]
            sources[lang] = {
                "url": data["wiki_page_url"],
                "license": TEXT_LICENSE,
                "license_url": TEXT_LICENSE_URL,
            }

    source_data = by_lang["en"] or by_lang["de"]
    picture = (
        await _fetch_picture(source_data, species.id, workspace_dir, force) if source_data else None
    )

    # 3. Write what was found in one short transaction
    values: dict[str, Any] = {}
    if descriptions:
        values["descriptions"] = descriptions
        values["description_sources"] = sources
        result.descriptions = descriptions
        result.description_sources = sources
    if picture is not None:
        image_path, attribution = picture
        values.update(
            image_path=image_path,
            image_source=attribution.page_url,
            image_author=attribution.author,
            image_license=attribution.license,
            image_license_url=attribution.license_url,
        )
        result.image_path = image_path
        result.image_source = attribution.page_url
        result.image_author = attribution.author
        result.image_license = attribution.license
        result.image_license_url = attribution.license_url
    if values:
        async with get_session() as session:
            await session.execute(
                update(Species)
                .where(Species.id == species.id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        log.info("wiki_species_updated", species=scientific_name)

    return result
