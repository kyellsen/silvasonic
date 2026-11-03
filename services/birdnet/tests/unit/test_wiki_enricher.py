"""Unit tests for the BirdNET wiki enricher module.

Tests cover:
- Slug conversion for filesystem-safe filenames
- Wikimedia thumbnail URL construction
- Wikipedia REST API response parsing
- Cache-hit behavior (DB+filesystem check)
- Error propagation semantics (caller-catches pattern)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from silvasonic.birdnet.wiki_enricher import (
    _make_thumb_url,
    _slug,
    enrich_if_needed,
    fetch_wiki_summary,
)

# ---------------------------------------------------------------------------
# Fake Wikipedia API responses (used instead of verbose mock chains)
# ---------------------------------------------------------------------------

_WIKI_BLACKBIRD_RESPONSE = {
    "extract_html": "<p>The common blackbird is a species of true thrush.</p>",
    "extract": "The common blackbird is a species of true thrush.",
    "thumbnail": {
        "source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Blackbird.jpg/320px-Blackbird.jpg"
    },
    "originalimage": {
        "source": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Blackbird.jpg"
    },
    "content_urls": {
        "desktop": {"page": "https://en.wikipedia.org/wiki/Common_blackbird"}
    },
    "description": "Species of true thrush",
}


def _fake_response(status_code: int, json_data: dict[str, Any] | None = None) -> MagicMock:
    """Build a minimal fake httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def _fake_client(response: MagicMock) -> AsyncMock:
    """Build a fake httpx.AsyncClient that returns a fixed response."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# §1  _slug() — filesystem-safe name conversion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSlug:
    """Slug conversion must produce lowercase, alphanumeric, underscore-only strings."""

    def test_two_word_scientific_name(self) -> None:
        """Standard binomial name → lowercase with underscore."""
        assert _slug("Turdus merula") == "turdus_merula"

    def test_single_genus_name(self) -> None:
        """Single-word genus → lowercase, no trailing underscores."""
        assert _slug("Corvus") == "corvus"

    def test_parentheses_stripped(self) -> None:
        """Special characters (subgenera in parens) must be replaced by underscores."""
        result = _slug("Parus (major)")
        assert result == "parus_major"

    def test_empty_input_returns_empty(self) -> None:
        """Edge case: empty string should not crash."""
        assert _slug("") == ""


# ---------------------------------------------------------------------------
# §2  _make_thumb_url() — Wikimedia image URL transformation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMakeThumbUrl:
    """Thumbnail URL builder must handle original, existing-thumb, and invalid URLs."""

    def test_converts_original_to_800px_thumb(self) -> None:
        """Standard Wikimedia commons URL → /thumb/…/800px-… variant."""
        original = "https://upload.wikimedia.org/wikipedia/commons/a/a9/Common_Blackbird.jpg"
        result = _make_thumb_url(original, 800)
        assert result is not None
        assert "/thumb/" in result
        assert "800px-Common_Blackbird.jpg" in result

    def test_resizes_existing_thumb_url(self) -> None:
        """Already-thumb URL with different width → replaces width prefix."""
        thumb = (
            "https://upload.wikimedia.org/wikipedia/commons/thumb/"
            "a/a9/Common_Blackbird.jpg/320px-Common_Blackbird.jpg"
        )
        result = _make_thumb_url(thumb, 800)
        assert result is not None
        assert "800px-Common_Blackbird.jpg" in result
        assert "320px" not in result

    def test_non_wikimedia_url_returns_none(self) -> None:
        """Non-Wikimedia image URLs must be rejected (safety check)."""
        assert _make_thumb_url("https://example.com/bird.jpg") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty input must not crash."""
        assert _make_thumb_url("") is None


# ---------------------------------------------------------------------------
# §3  fetch_wiki_summary() — Wikipedia REST API interaction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchWikiSummary:
    """Wikipedia API fetcher must parse responses correctly and handle errors gracefully."""

    @pytest.mark.asyncio
    async def test_200_returns_parsed_summary(self) -> None:
        """Successful response → extract_html, wiki_page_url, original_image_url populated."""
        client = _fake_client(_fake_response(200, _WIKI_BLACKBIRD_RESPONSE))

        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            result = await fetch_wiki_summary("Turdus merula", "en")

        assert result is not None
        assert "true thrush" in result["extract_html"]
        assert result["wiki_page_url"] == "https://en.wikipedia.org/wiki/Common_blackbird"
        assert result["original_image_url"] == (
            "https://upload.wikimedia.org/wikipedia/commons/a/a9/Blackbird.jpg"
        )

    @pytest.mark.asyncio
    async def test_404_species_not_found_returns_none(self) -> None:
        """Unknown species → None return (no exception)."""
        client = _fake_client(_fake_response(404))

        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            result = await fetch_wiki_summary("Nonexistent birdus", "en")

        assert result is None

    @pytest.mark.asyncio
    async def test_missing_optional_fields_do_not_crash(self) -> None:
        """Response with missing thumbnail/originalimage → fields are None, no crash."""
        minimal = {"extract_html": "<p>A bird.</p>", "extract": "A bird."}
        client = _fake_client(_fake_response(200, minimal))

        with patch("silvasonic.birdnet.wiki_enricher.httpx.AsyncClient", return_value=client):
            result = await fetch_wiki_summary("Parus major", "de")

        assert result is not None
        assert result["extract_html"] == "<p>A bird.</p>"
        assert result["thumbnail_url"] is None
        assert result["original_image_url"] is None


# ---------------------------------------------------------------------------
# §4  enrich_if_needed() — orchestration with DB cache check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnrichIfNeeded:
    """Enrichment orchestrator must skip HTTP calls on cache-hit and propagate errors."""

    @pytest.mark.asyncio
    async def test_cache_hit_with_image_skips_http(self, tmp_path: Path) -> None:
        """When Taxonomy has description + image file exists → no Wikipedia API call."""
        # Arrange: fake image on disk
        img_dir = tmp_path / "wiki" / "img"
        img_dir.mkdir(parents=True)
        (img_dir / "turdus_merula.jpg").write_bytes(b"\xff\xd8fake-jpeg")

        # Arrange: fake Taxonomy DB row with cached data
        taxonomy = MagicMock()
        taxonomy.description = {"en": "<p>Blackbird info.</p>", "de": "<p>Amsel Info.</p>"}
        taxonomy.image_path = "turdus_merula.jpg"
        taxonomy.image_source = "https://upload.wikimedia.org/…/Blackbird.jpg"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = taxonomy

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        # Act
        with patch("silvasonic.birdnet.wiki_enricher.fetch_wiki_summary") as mock_fetch:
            result = await enrich_if_needed(
                "Turdus merula_Eurasian Blackbird", session, tmp_path
            )

        # Assert: no HTTP call, cached data returned
        mock_fetch.assert_not_called()
        assert result.description["en"] == "<p>Blackbird info.</p>"
        assert result.description["de"] == "<p>Amsel Info.</p>"
        assert result.image_url is not None
        assert "turdus_merula.jpg" in result.image_url

    @pytest.mark.asyncio
    async def test_cache_hit_missing_image_returns_none_url(self, tmp_path: Path) -> None:
        """When Taxonomy has description+image_path but file is gone → image_url=None (graceful)."""
        # Arrange: Taxonomy says image exists, but file is NOT on disk
        taxonomy = MagicMock()
        taxonomy.description = {"en": "<p>Robin info.</p>"}
        taxonomy.image_path = "erithacus_rubecula.jpg"
        taxonomy.image_source = "https://example.com/robin.jpg"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = taxonomy

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await enrich_if_needed(
            "Erithacus rubecula_European Robin", session, tmp_path
        )

        # Assert: cache-hit returned but image_url is None (file doesn't exist)
        assert result.description == {"en": "<p>Robin info.</p>"}
        assert result.image_url is None

    @pytest.mark.asyncio
    async def test_db_error_propagates_to_caller(self, tmp_path: Path) -> None:
        """DB errors must propagate — service.py catches them in try/except."""
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=ConnectionError("DB unavailable"))

        with pytest.raises(ConnectionError, match="DB unavailable"):
            await enrich_if_needed(
                "Turdus merula_Eurasian Blackbird", session, tmp_path
            )

    @pytest.mark.asyncio
    async def test_label_without_underscore_uses_full_string(self, tmp_path: Path) -> None:
        """Labels without underscore (edge case) → entire label used as scientific name."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None  # No Taxonomy

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        with patch("silvasonic.birdnet.wiki_enricher.fetch_wiki_summary") as mock_fetch:
            mock_fetch.return_value = None
            await enrich_if_needed("Corvus", session, tmp_path)

        # Verify the fetch was called with the full label as scientific name
        call_args = mock_fetch.call_args_list[0]
        assert call_args[0][0] == "Corvus"
