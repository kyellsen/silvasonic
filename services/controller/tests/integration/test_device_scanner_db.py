"""Integration tests: DeviceScanner + upsert_microphone ↔ real DB.

Verifies that DeviceScanner can read ``/proc/asound/cards`` on the host
and that ``upsert_microphone`` correctly persists microphone rows into PostgreSQL.

Tests are **skipped** when:
- ``/proc/asound/cards`` does not exist (CI / non-Linux)
- No USB-Audio card is present (optional, scan returns empty list)
- ``station_db`` fixture is unavailable
"""

from __future__ import annotations

import json
import pathlib
from pathlib import Path

import pytest
from silvasonic.controller.device_scanner import (
    DeviceInfo,
    DeviceScanner,
)
from silvasonic.controller.microphone_repository import upsert_microphone
from silvasonic.core.database.session import create_station_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_CARDS_PATH = pathlib.Path("/proc/asound/cards")
_CARDS_AVAILABLE = _CARDS_PATH.exists()

pytestmark = [
    pytest.mark.integration,
]


@pytest.mark.skipif(
    not _CARDS_AVAILABLE,
    reason="/proc/asound/cards not found (not Linux or no ALSA)",
)
class TestDeviceScannerHostRead:
    """Verify DeviceScanner reads real /proc/asound/cards."""

    def test_scan_returns_list(self) -> None:
        """scan_all() returns a list (possibly empty if no USB devices)."""
        scanner = DeviceScanner()
        devices = scanner.scan_all()

        assert isinstance(devices, list)
        for d in devices:
            assert isinstance(d, DeviceInfo)
            assert d.alsa_card_index >= 0
            assert d.alsa_device.startswith("hw:")

    @pytest.mark.system_hw_auto
    def test_scan_usb_devices_have_vendor_info(self) -> None:
        """USB-Audio devices should have vendor/product IDs (if sysfs is accessible)."""
        scanner = DeviceScanner()
        devices = scanner.scan_all()

        usb_devices = [d for d in devices if d.usb_vendor_id]
        if not usb_devices:
            pytest.skip("No USB-Audio devices with vendor info detected")

        for d in usb_devices:
            assert d.usb_vendor_id is not None
            assert d.usb_product_id is not None
            assert len(d.usb_vendor_id) == 4  # hex VID


class TestUpsertDeviceDB:
    """Verify upsert_microphone writes to real PostgreSQL."""

    async def test_upsert_inserts_new_device(
        self,
        station_db: Path,
    ) -> None:
        """upsert_microphone creates a new microphone row in the DB."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        device_info = DeviceInfo(
            alsa_card_index=99,
            alsa_name="IntegrationTestMic",
            alsa_device="hw:99,0",
            usb_vendor_id="dead",
            usb_product_id="beef",
            usb_serial="INT-TEST-001",
        )

        async with session_factory() as session:
            await upsert_microphone(device_info, session)
            await session.commit()

        # Verify in the DB
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT hardware_id, connection_state, enrollment_state, model "
                    "FROM microphones WHERE hardware_id = 'dead-beef-INT-TEST-001'"
                )
            )
            row = result.one_or_none()

        await engine.dispose()

        assert row is not None, "Microphone not found in DB after upsert"
        assert row[0] == "dead-beef-INT-TEST-001"  # hardware_id
        assert row[1] == "connected"  # connection_state
        assert row[2] == "pending"  # enrollment_state
        assert row[3] == "IntegrationTestMic"  # model

    @pytest.mark.system_hw_auto
    async def test_detects_real_hardware_primary_mic(
        self,
        station_db: Path,
    ) -> None:
        """Calling upsert_microphone twice does not create duplicates."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        device_info = DeviceInfo(
            alsa_card_index=88,
            alsa_name="IdempotentMic",
            alsa_device="hw:88,0",
            usb_vendor_id="1234",
            usb_product_id="5678",
            usb_serial="IDEM-001",
        )

        # Insert twice
        async with session_factory() as session:
            await upsert_microphone(device_info, session)
            await session.commit()

        async with session_factory() as session:
            await upsert_microphone(device_info, session)
            await session.commit()

        # Verify only one row
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT count(*) FROM microphones WHERE hardware_id = '1234-5678-IDEM-001'")
            )
            count = result.scalar_one()

        await engine.dispose()

        assert count == 1, f"Expected 1 microphone row, got {count}"

    async def test_upsert_with_profile_auto_enroll(
        self,
        tmp_path: Path,
        station_db: Path,
    ) -> None:
        """upsert_microphone with profile_slug sets enrollment to 'enrolled'."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # First seed a profile so FK constraint is satisfied
        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "test_profile.yml").write_text(
            """
schema_version: "2.0"
slug: test_profile
name: Test Profile
description: For integration test.
audio:
  sample_rate_hz: 48000
  channels: 1
  sample_format: S16LE
processing:
  gain_db: 0.0
  chunk_frames: 4096
stream:
  raw_enabled: true
  processed_enabled: true
  live_stream_enabled: false
  segment_duration_s: 15
""",
            encoding="utf-8",
        )
        bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)
        async with session_factory() as session:
            await bootstrapper.seed(session)
            await session.commit()

        # Now upsert device with auto-enroll
        device_info = DeviceInfo(
            alsa_card_index=77,
            alsa_name="AutoEnrollMic",
            alsa_device="hw:77,0",
            usb_vendor_id="abcd",
            usb_product_id="ef01",
            usb_serial="AUTO-001",
        )

        async with session_factory() as session:
            await upsert_microphone(
                device_info,
                session,
                profile_slug="test_profile",
                enrollment_state="enrolled",
            )
            await session.commit()

        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT enrollment_state, profile_slug "
                    "FROM microphones WHERE hardware_id = 'abcd-ef01-AUTO-001'"
                )
            )
            row = result.one_or_none()

        await engine.dispose()

        assert row is not None
        assert row[0] == "enrolled"
        assert row[1] == "test_profile"

    async def test_upsert_microphone_updates_volatile_hardware_facts(
        self,
        station_db: Path,
    ) -> None:
        """TDD Test for Issue 003: Volatile ALSA Configuration Drift."""
        engine = create_station_engine(station_db)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # --- SCHRITT 1: Erstes Einstecken (Initial Setup) ---
        initial_info = DeviceInfo(
            alsa_card_index=1,
            alsa_name="TestMic",
            alsa_device="hw:1,0",
            usb_vendor_id="1234",
            usb_product_id="5678",
            usb_serial="SN-999",
            usb_bus_path="1-1.1",
        )
        async with session_factory() as session:
            await upsert_microphone(initial_info, session)
            await session.commit()

        # --- SCHRITT 2: Re-Plug (Simulated Drift) ---
        new_info = DeviceInfo(
            alsa_card_index=2,
            alsa_name="TestMic (Updated)",
            alsa_device="hw:2,0",
            usb_vendor_id="1234",
            usb_product_id="5678",
            usb_serial="SN-999",
            usb_bus_path="1-1.2",
        )
        async with session_factory() as session:
            await upsert_microphone(new_info, session)
            await session.commit()

        # --- SCHRITT 3: Verify DB updates using RAW SQL (Consistency) ---
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT model, hardware FROM microphones WHERE hardware_id = '1234-5678-SN-999'"
                )
            )
            row = result.one_or_none()

        await engine.dispose()

        assert row is not None
        model = row[0]
        hardware = json.loads(row[1])  # raw SQL: JSON is TEXT in SQLite

        # Verify changes were persisted by SQLAlchemy correctly
        assert model == "TestMic (Updated)", "Model string did not update!"
        assert hardware["alsa_device"] == "hw:2,0", "ALSA device string did not update!"
        assert hardware["alsa_card_index"] == 2, "ALSA card index did not update!"
        assert hardware["usb_bus_path"] == "1-1.2", "USB bus path did not update!"
