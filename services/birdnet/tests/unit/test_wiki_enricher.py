"""Unit tests for the BirdNET wiki enricher module.

Tests cover:
- Wikimedia thumbnail URL construction and Commons file names
- Wikipedia and Commons API response parsing: plain text only
- What is skipped: no species row, sound classes, recent lookups, complete rows
- What a lookup stores: plain-text descriptions with source and licence,
  a Commons picture with author and licence — nothing that cannot be attributed
- No database transaction is open while the network is used (ADR-0037)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.birdnet import wiki_enricher
from silvasonic.birdnet.wiki_enricher import (
    TEXT_LICENSE,
    ImageAttribution,
    _commons_file_name,
    _make_thumb_url,
    enrich_if_needed,
    fetch_commons_attribution,
    fetch_wiki_summary,
    plain_text,
)

BLACKBIRD = "Turdus merula_Eurasian Blackbird"
COMMONS_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/a/a9/Blackbird.jpg"
LOCAL_IMAGE = "https://upload.wikimedia.org/wikipedia/en/b/b1/Logo.png"
ATTRIBUTION = ImageAttribution(
    author="Andreas Trepte",
    license="CC BY-SA 2.5",
    license_url="https://creativecommons.org/licenses/by-sa/2.5",
    page_url="https://commons.wikimedia.org/wiki/File:Blackbird.jpg",
)

_WIKI_BLACKBIRD_RESPONSE = {
    "extract_html": "<p>The common <b>blackbird</b> is a species of true thrush.</p>",
    "extract": "The common blackbird is a species of true thrush.",
    "thumbnail": {
        "source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Blackbird.jpg/320px-Blackbird.jpg"
    },
    "originalimage": {"source": COMMONS_IMAGE},
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Common_blackbird"}},
    "description": "Species of true thrush",
}

_COMMONS_RESPONSE = {
    "query": {
        "pages": {
            "1": {
                "imageinfo": [
                    {
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Blackbird.jpg",
                        "extmetadata": {
                            "Artist": {
                                "value": '<a href="//commons…/User:Merops">Andreas Trepte</a>'
                            },
                            "LicenseShortName": {"value": "CC BY-SA 2.5"},
                            "LicenseUrl": {
                                "value": "https://creativecommons.org/licenses/by-sa/2.5"
                            },
                        },
                    }
                ]
            }
        }
    }
}


def _summary(lang: str, image: str | None = COMMONS_IMAGE) -> dict[str, Any]:
    """What ``fetch_wiki_summary`` returns for the blackbird."""
    return {
        "extract": f"Blackbird ({lang}).",
        "thumbnail_url": None,
        "original_image_url": image,
        "wiki_page_url": f"https://{lang}.wikipedia.org/wiki/Blackbird",
        "short_description": "",
    }


def _fake_response(status_code: int, json_data: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def _fake_client(response: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _species_row(
    species_id: str = "turdus-merula",
    *,
    category: str = "bird",
    descriptions: dict[str, str] | None = None,
    image_path: str | None = None,
) -> MagicMock:
    """A stand-in for a ``Species`` ORM row."""
    row = MagicMock()
    row.id = species_id
    row.category = category
    row.descriptions = descriptions if descriptions is not None else {}
    row.description_sources = {}
    row.image_path = image_path
    row.image_source = None
    row.image_author = None
    row.image_license = None
    row.image_license_url = None
    return row


class FakeDatabase:
    """Patches ``get_session``: serves one species row and records the write.

    ``open`` is True while a session is open, so a fake network call can
    check that no transaction is held during it.
    """

    def __init__(self, row: MagicMock | None) -> None:
        """Serve ``row`` to every species lookup."""
        self.row = row
        self.open = False
        self.writes: list[Any] = []

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncMock]:
        self.open = True
        lookup = MagicMock()
        lookup.scalars.return_value.first.return_value = self.row
        session = AsyncMock()

        async def execute(stmt: Any) -> Any:
            if stmt.is_select:
                return lookup
            self.writes.append(stmt.compile().params)
            return MagicMock()

        session.execute = AsyncMock(side_effect=execute)
        try:
            yield session
        finally:
            self.open = False


@pytest.fixture(autouse=True)
def _fresh_lookup_state() -> Iterator[None]:
    """Each test starts without remembered lookups and without real sleeps."""
    wiki_enricher._next_attempt.clear()
    with patch("silvasonic.birdnet.wiki_enricher.asyncio.sleep", new=AsyncMock()):
        yield
    wiki_enricher._next_attempt.clear()


def _patched(
    db: FakeDatabase, *, summary: Any, attribution: Any = ATTRIBUTION, download: Any = True
) -> tuple[AsyncMock, tuple[Any, ...]]:
    """Patch database, Wikipedia, Commons and the download; each network fake checks the lock."""

    async def fetch(name: str, lang: str) -> Any:
        assert not db.open, "Wikipedia called inside a database transaction"
        return summary(lang) if callable(summary) else summary

    async def commons(url: str) -> Any:
        assert not db.open, "Commons called inside a database transaction"
        return attribution

    async def fake_download(url: str, dest: Path) -> bool:
        assert not db.open, "download inside a database transaction"
        if download:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\xff\xd8fake-jpeg")
        return bool(download)

    fetch_mock = AsyncMock(side_effect=fetch)
    return (
        fetch_mock,
        (
            patch("silvasonic.birdnet.wiki_enricher.get_session", side_effect=db.session),
            patch("silvasonic.birdnet.wiki_enricher.fetch_wiki_summary", new=fetch_mock),
            patch(
                "silvasonic.birdnet.wiki_enricher.fetch_commons_attribution", side_effect=commons
            ),
            patch("silvasonic.birdnet.wiki_enricher._download_image", side_effect=fake_download),
        ),
    )


async def _run(db: FakeDatabase, tmp_path: Path, label: str = BLACKBIRD, **kwargs: Any) -> Any:
    fetch, patches = _patched(db, **kwargs)
    with patches[0], patches[1], patches[2], patches[3]:
        result = await enrich_if_needed(label, tmp_path)
    return result, fetch


# ---------------------------------------------------------------------------
# §1  URLs and text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUrlsAndText:
    """Thumbnail URLs, Commons file names, and HTML reduced to text."""

    def test_converts_original_to_800px_thumb(self) -> None:
        assert _make_thumb_url(COMMONS_IMAGE) == (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Blackbird.jpg/800px-Blackbird.jpg"
        )

    def test_resizes_existing_thumb_url(self) -> None:
        url = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Blackbird.jpg/320px-Blackbird.jpg"
        assert _make_thumb_url(url) == (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Blackbird.jpg/800px-Blackbird.jpg"
        )

    def test_non_wikimedia_url_returns_none(self) -> None:
        assert _make_thumb_url("https://example.com/bird.jpg") is None
        assert _make_thumb_url("") is None

    def test_commons_file_name_from_original_and_thumb(self) -> None:
        assert _commons_file_name(COMMONS_IMAGE) == "File:Blackbird.jpg"
        thumb = (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/"
            "Turdus%20merula.jpg/320px-Turdus%20merula.jpg"
        )
        assert _commons_file_name(thumb) == "File:Turdus merula.jpg"

    def test_plain_text_drops_markup_and_scripts_become_harmless_text(self) -> None:
        assert plain_text("<p>A <b>bird</b> &amp; its song.</p>") == "A bird & its song."
        assert "<" not in plain_text('<img src=x onerror="alert(1)">Hi<script>x</script>')


# ---------------------------------------------------------------------------
# §2  API parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestFetchers:
    """Wikipedia summaries and Commons attribution are parsed into plain values."""

    async def test_summary_is_plain_text(self) -> None:
        client = _fake_client(_fake_response(200, _WIKI_BLACKBIRD_RESPONSE))
        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            result = await fetch_wiki_summary("Turdus merula", "en")

        assert result is not None
        assert result["extract"] == "The common blackbird is a species of true thrush."
        assert "extract_html" not in result
        assert result["wiki_page_url"] == "https://en.wikipedia.org/wiki/Common_blackbird"
        assert result["original_image_url"] == COMMONS_IMAGE

    async def test_unknown_species_returns_none(self) -> None:
        client = _fake_client(_fake_response(404))
        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            assert await fetch_wiki_summary("Nonexistent birdus", "en") is None

    async def test_commons_attribution_parsed_to_text(self) -> None:
        client = _fake_client(_fake_response(200, _COMMONS_RESPONSE))
        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            attribution = await fetch_commons_attribution(COMMONS_IMAGE)

        assert attribution == ATTRIBUTION
        assert client.get.await_args.kwargs["params"]["titles"] == "File:Blackbird.jpg"

    async def test_commons_without_licence_gives_nothing(self) -> None:
        response = {
            "query": {"pages": {"1": {"imageinfo": [{"descriptionurl": "x", "extmetadata": {}}]}}}
        }
        client = _fake_client(_fake_response(200, response))
        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            assert await fetch_commons_attribution(COMMONS_IMAGE) is None

    async def test_local_wikipedia_upload_is_never_asked_about(self) -> None:
        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient") as client_cls:
            assert await fetch_commons_attribution(LOCAL_IMAGE) is None
        client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# §3  enrich_if_needed() — what is skipped
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestEnrichSkipsLookup:
    """No network call when the row is complete, absent, not a species, or recent."""

    async def test_complete_row_with_image_on_disk(self, tmp_path: Path) -> None:
        image = tmp_path / "wiki" / "img" / "turdus-merula.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"jpg")
        row = _species_row(
            descriptions={"en": "A thrush."}, image_path="wiki/img/turdus-merula.jpg"
        )
        db = FakeDatabase(row)

        result, fetch = await _run(db, tmp_path, summary=_summary)

        fetch.assert_not_awaited()
        assert result.image_path == "wiki/img/turdus-merula.jpg"
        assert db.writes == []

    async def test_no_species_row_means_no_lookup(self, tmp_path: Path) -> None:
        db = FakeDatabase(None)
        _, fetch = await _run(db, tmp_path, summary=_summary)
        fetch.assert_not_awaited()
        assert db.writes == []

    async def test_sound_class_is_not_looked_up(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row("engine", category="other"))
        _, fetch = await _run(db, tmp_path, "Engine_Engine", summary=_summary)
        fetch.assert_not_awaited()

    async def test_failed_lookup_is_not_repeated_at_once(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())
        _, fetch = await _run(db, tmp_path, summary=None)
        _, again = await _run(db, tmp_path, summary=None)
        assert fetch.await_count == 2  # EN + DE once
        again.assert_not_awaited()

    async def test_lookup_is_repeated_after_the_retry_interval(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())
        await _run(db, tmp_path, summary=None)
        wiki_enricher._next_attempt["turdus-merula"] = 0.0
        _, again = await _run(db, tmp_path, summary=None)
        assert again.await_count == 2


# ---------------------------------------------------------------------------
# §4  enrich_if_needed() — what a lookup stores
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestEnrichStores:
    """Plain text with its source, a picture with its attribution, nothing unattributable."""

    async def test_lookup_stores_text_sources_and_attributed_picture(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())

        result, fetch = await _run(db, tmp_path, summary=_summary)

        assert fetch.await_count == 2
        (write,) = db.writes
        assert write["descriptions"] == {"en": "Blackbird (en).", "de": "Blackbird (de)."}
        assert write["description_sources"]["de"] == {
            "url": "https://de.wikipedia.org/wiki/Blackbird",
            "license": TEXT_LICENSE,
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        }
        assert write["image_path"] == "wiki/img/turdus-merula.jpg"
        assert write["image_source"] == ATTRIBUTION.page_url
        assert write["image_author"] == "Andreas Trepte"
        assert write["image_license"] == "CC BY-SA 2.5"
        assert result.image_license == "CC BY-SA 2.5"
        assert (tmp_path / "wiki" / "img" / "turdus-merula.jpg").exists()

    async def test_picture_without_attribution_is_not_kept(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())

        result, _ = await _run(db, tmp_path, summary=_summary, attribution=None)

        (write,) = db.writes
        assert "image_path" not in write
        assert result.image_path is None
        assert not (tmp_path / "wiki").exists()
        assert write["descriptions"]["en"] == "Blackbird (en)."

    async def test_local_wikipedia_picture_is_never_downloaded(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())

        def local(lang: str) -> dict[str, Any]:
            return _summary(lang, image=LOCAL_IMAGE)

        result, _ = await _run(db, tmp_path, summary=local)

        (write,) = db.writes
        assert "image_path" not in write
        assert result.image_path is None

    async def test_failed_download_leaves_no_image(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())
        result, _ = await _run(db, tmp_path, summary=_summary, download=False)
        (write,) = db.writes
        assert "image_path" not in write
        assert result.image_path is None

    async def test_nothing_found_writes_nothing(self, tmp_path: Path) -> None:
        db = FakeDatabase(_species_row())
        await _run(db, tmp_path, summary=None)
        assert db.writes == []

    async def test_db_error_propagates_to_caller(self, tmp_path: Path) -> None:
        """BirdNET catches and logs; the enricher does not hide a database failure."""

        @asynccontextmanager
        async def broken() -> AsyncGenerator[Any]:
            raise ConnectionError("DB unavailable")
            yield  # pragma: no cover

        with (
            patch("silvasonic.birdnet.wiki_enricher.get_session", side_effect=broken),
            pytest.raises(ConnectionError),
        ):
            await enrich_if_needed(BLACKBIRD, tmp_path)
