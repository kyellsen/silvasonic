"""Integration tests for the Indexer module.

Tests WAV indexing end-to-end against a real PostgreSQL database
(Testcontainer). Creates synthetic WAV files, runs the Indexer, and
verifies ``recordings`` rows in the database.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import pytest
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.processor import indexer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


def _build_async_url(container: PostgresContainer) -> str:
    """Build an asyncpg connection URL from a testcontainer."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic_test"


def _create_wav(path: Path, *, duration_s: float = 1.0, sample_rate: int = 48000) -> None:
    """Create a minimal valid WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


def _setup_workspace(base: Path, sensor: str = "mic-01", count: int = 2) -> list[Path]:
    """Create a mock workspace with WAV files and returns created paths."""
    created = []
    for i in range(count):
        for stream in ("processed", "raw"):
            d = base / sensor / "data" / stream
            d.mkdir(parents=True, exist_ok=True)
            wav = d / f"2026-01-01T0{i}-00-00_10s.wav"
            _create_wav(wav, duration_s=10.0)
            if stream == "processed":
                created.append(wav)
    return created


async def _seed_device(session: AsyncSession, name: str = "mic-01") -> None:
    """Insert a test device into the devices table."""
    await session.execute(
        text("""
            INSERT INTO devices (name, serial_number, model, config)
            VALUES (:name, :sn, 'TestMic', '{}')
            ON CONFLICT (name) DO NOTHING
        """),
        {"name": name, "sn": f"SN-{name}"},
    )
    await session.commit()


@pytest.mark.integration
class TestIndexerIntegration:
    """Verify Indexer end-to-end with real PostgreSQL."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, postgres_container: Any) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("POSTGRES_HOST", postgres_container.get_container_host_ip())
        monkeypatch.setenv("POSTGRES_PORT", str(postgres_container.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_USER", "silvasonic")
        monkeypatch.setenv("POSTGRES_PASSWORD", "silvasonic")
        monkeypatch.setenv("POSTGRES_DB", "silvasonic_test")

    async def test_new_wav_indexed(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Synthetic WAVs in workspace → Indexer picks up → verify recordings rows."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_device(session, "mic-01")

        _setup_workspace(tmp_path, "mic-01", count=2)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        assert result.new == 2
        assert result.skipped == 0
        assert result.errors == 0

        # Verify rows in DB
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            count = rows.scalar()
            assert count == 2

        # Cleanup
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM recordings"))
            await conn.execute(text("DELETE FROM devices WHERE name = 'mic-01'"))
        await engine.dispose()

    async def test_idempotent_reindex(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Running Indexer twice on same files → no duplicate rows."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_device(session, "mic-01")

        _setup_workspace(tmp_path, "mic-01", count=1)

        # First run
        async with factory() as session:
            r1 = await indexer.index_recordings(session, tmp_path)
        assert r1.new == 1

        # Second run — same files
        async with factory() as session:
            r2 = await indexer.index_recordings(session, tmp_path)
        assert r2.new == 0
        assert r2.skipped == 1

        # Verify only 1 row
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            assert rows.scalar() == 1

        # Cleanup
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM recordings"))
            await conn.execute(text("DELETE FROM devices WHERE name = 'mic-01'"))
        await engine.dispose()

    async def test_multiple_sensors_indexed(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Files from two sensor directories → correct sensor_id per row."""
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await _seed_device(session, "mic-01")
            await _seed_device(session, "mic-02")

        _setup_workspace(tmp_path, "mic-01", count=1)
        _setup_workspace(tmp_path, "mic-02", count=1)

        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        assert result.new == 2

        # Verify sensor_ids
        async with factory() as session:
            rows = await session.execute(
                text("SELECT sensor_id FROM recordings ORDER BY sensor_id")
            )
            sensors = [r[0] for r in rows.fetchall()]
            assert sensors == ["mic-01", "mic-02"]

        # Cleanup
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM recordings"))
            await conn.execute(text("DELETE FROM devices"))
        await engine.dispose()
