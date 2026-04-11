"""Cross-service contract test: Controller workspace naming vs. Processor indexing.

Validates the implicit contract between Controller and Processor:
the workspace directory name must be stored in ``devices.workspace_name``
so the Processor can resolve it to the device's stable identity.

This test reproduces the exact production flow:
  1. Controller creates a Device row via ``upsert_device()``
  2. Controller computes workspace_name via ``generate_workspace_name()``
  3. Controller derives workspace dir via ``build_recorder_spec()``
  4. Recorder writes WAV files into that workspace dir
  5. Processor's ``index_recordings()`` looks up by workspace_name

If the contract holds, recordings are indexed.
If not, the Processor silently skips every file (``device_not_registered``).

See: Log Analysis Report 2026-03-30 — Bug #1 (Name-Mismatch).
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import pytest
from silvasonic.controller.container_spec import build_recorder_spec, generate_workspace_name
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.core.database.session import _get_engine, _get_session_factory
from silvasonic.processor import indexer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


def _build_async_url(container: PostgresContainer) -> str:
    """Build an asyncpg connection URL from a testcontainer."""
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://silvasonic:silvasonic@{host}:{port}/silvasonic_test"


def _create_wav(path: Path, *, duration_s: float = 10.0, sample_rate: int = 48000) -> None:
    """Create a minimal valid WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


@pytest.mark.integration
class TestWorkspaceDeviceContract:
    """Contract test: workspace_name must bridge workspace dir to devices.name.

    This test simulates the exact production flow:

    1. Scan a USB device (simulated DeviceInfo)
    2. Upsert it into the devices table (Controller's device_repository)
    3. Compute workspace_name (Controller's generate_workspace_name)
    4. Build a Recorder container spec (Controller's container_spec)
    5. Create WAV files in the workspace dir derived from the spec
    6. Run the Processor's index_recordings()
    7. Assert that recordings are actually indexed
    """

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch: pytest.MonkeyPatch, postgres_container: Any) -> None:
        """Inject testcontainer DB credentials into environment."""
        _get_engine.cache_clear()
        _get_session_factory.cache_clear()
        monkeypatch.setenv("SILVASONIC_DB_HOST", postgres_container.get_container_host_ip())
        monkeypatch.setenv("SILVASONIC_DB_PORT", str(postgres_container.get_exposed_port(5432)))
        monkeypatch.setenv("POSTGRES_USER", "silvasonic")
        monkeypatch.setenv("POSTGRES_PASSWORD", "silvasonic")
        monkeypatch.setenv("POSTGRES_DB", "silvasonic_test")

    async def test_controller_workspace_matches_processor_lookup(
        self, postgres_container: PostgresContainer, tmp_path: Path
    ) -> None:
        """Recordings in Controller-created workspace are indexed by Processor.

        This is the primary contract test. It uses REAL hardware identifiers
        (Ultramic 384K EVO) to match the exact production scenario from the
        log analysis.
        """
        url = _build_async_url(postgres_container)
        engine = create_async_engine(url, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # --- Step 1: Simulate Controller's device scan ---
        device_info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="UltraMic384K_EVO 16bit r0",
            alsa_device="hw:2,0",
            usb_vendor_id="0869",
            usb_product_id="0389",
            usb_serial="00000000034F",
            usb_bus_path="3-6",
        )

        # --- Step 2: Controller upserts device + seeds profile ---
        async with factory() as session:
            # Seed the microphone profile (like the real Seeder does)
            await session.execute(
                text("""
                    INSERT INTO microphone_profiles (slug, name, config, is_system)
                    VALUES (:slug, :name, :config, TRUE)
                    ON CONFLICT (slug) DO NOTHING
                """),
                {
                    "slug": "ultramic_384_evo",
                    "name": "Ultramic 384 EVO",
                    "config": '{"audio": {"sample_rate": 384000, "channels": 1}}',
                },
            )
            await session.commit()

            # Upsert device (like the real Controller does)
            device = await upsert_device(
                device_info,
                session,
                profile_slug="ultramic_384_evo",
                enrollment_status="enrolled",
            )

            # Simulate what the reconciler does: compute and persist workspace_name
            ws = generate_workspace_name("ultramic_384_evo", device)
            device.workspace_name = ws
            await session.commit()

            # Capture what the Controller stored
            db_device_name = device.name
            db_workspace_name = device.workspace_name

        # --- Step 3: Controller builds the Recorder spec ---
        async with factory() as session:
            from silvasonic.core.database.models.profiles import (
                MicrophoneProfile as MicProfileDB,
            )

            profile = await session.get(MicProfileDB, "ultramic_384_evo")
            assert profile is not None

            from silvasonic.core.database.models.system import Device

            device_row = await session.get(Device, db_device_name)
            assert device_row is not None

            spec = build_recorder_spec(device_row, profile)
            workspace_dir = spec.name.removeprefix("silvasonic-recorder-")

        # --- Step 4: Recorder creates WAV files in the workspace ---
        processed_dir = tmp_path / workspace_dir / "data" / "processed"
        raw_dir = tmp_path / workspace_dir / "data" / "raw"
        _create_wav(processed_dir / "2026-03-30T14-52-47Z_15s_1a2b3c4d_00000000.wav")
        _create_wav(raw_dir / "2026-03-30T14-52-47Z_15s_1a2b3c4d_00000000.wav")

        # --- Step 5: Processor indexes the workspace ---
        async with factory() as session:
            result = await indexer.index_recordings(session, tmp_path)

        # --- Step 6: Assert contract ---
        assert result.new >= 1, (
            f"Contract violation: Processor failed to index recordings. "
            f"devices.name={db_device_name!r}, "
            f"devices.workspace_name={db_workspace_name!r}, "
            f"workspace_dir={workspace_dir!r}, "
            f"result={result}"
        )

        # Verify the recording is actually in the DB
        async with factory() as session:
            rows = await session.execute(text("SELECT COUNT(*) FROM recordings"))
            count = rows.scalar() or 0
            assert count >= 1, f"Expected at least 1 recording in DB, got {count}"

        await engine.dispose()
