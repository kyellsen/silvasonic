"""Integration test: Full Recorder Spawn Flow (scan → container start).

Verifies the complete chain of components with a **real database**
(testcontainers PostgreSQL) and **mocked hardware** (ALSA + Podman):

    Mock /proc/asound/cards
      → DeviceScanner.scan_all()
      → ProfileMatcher.match()
      → upsert_device() [real DB]
      → DeviceStateEvaluator.evaluate() [real DB]
      → ContainerManager.start() [mock Podman]

This is an **integration** test (not E2E) because it stays within the
Controller service boundary and does not involve UI or cross-service HTTP.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceInfo, DeviceScanner, UsbInfo
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.reconciler import DeviceStateEvaluator
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = [
    pytest.mark.integration,
]

# -----------------------------------------------------------------------
# Mock device constants — single source of truth for this test module.
# These are *fictional* VID/PID values, intentionally different from the
# real production seed (0869:0389) so unit/integration tests stay isolated.
# -----------------------------------------------------------------------

_MOCK_VID = "16d0"
_MOCK_PID = "0b40"
_MOCK_ALSA_NAME = "UltraMic 384K"
_MOCK_PROFILE_SLUG = "ultramic_384k"

MOCK_ASOUND_CARDS = (
    " 0 [PCH             ]: HDA-Intel - HDA Intel PCH\n"
    "                      HDA Intel PCH at 0xf7200000 irq 32\n"
    f" 2 [UltraMic384K    ]: USB-Audio - {_MOCK_ALSA_NAME}\n"
    "                      Dodotronic UltraMic384K at usb-0000:00:14-2\n"
)


def _device_id(serial: str) -> str:
    """Build the expected stable_device_id for a mock device."""
    return f"{_MOCK_VID}-{_MOCK_PID}-{serial}"


def _make_device(serial: str, *, card_index: int = 2) -> DeviceInfo:
    """Create a DeviceInfo with the module-level mock VID/PID constants."""
    return DeviceInfo(
        alsa_card_index=card_index,
        alsa_name=_MOCK_ALSA_NAME,
        alsa_device=f"hw:{card_index},0",
        usb_vendor_id=_MOCK_VID,
        usb_product_id=_MOCK_PID,
        usb_serial=serial,
    )


def _mock_usb_info(serial: str) -> UsbInfo:
    """Create a UsbInfo with the module-level mock VID/PID constants."""
    return UsbInfo(
        vendor_id=_MOCK_VID,
        product_id=_MOCK_PID,
        serial=serial,
        bus_path="1-2",
    )


def _seed_matching_profile(tmp_path: Path) -> Path:
    """Create a profile YAML that matches the mock device via USB VID/PID."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(exist_ok=True)
    (profiles_dir / f"{_MOCK_PROFILE_SLUG}.yml").write_text(
        f"""
schema_version: "1.0"
slug: {_MOCK_PROFILE_SLUG}
name: {_MOCK_ALSA_NAME}
description: Dodotronic {_MOCK_ALSA_NAME} USB microphone.
audio:
  sample_rate: 384000
  channels: 1
  format: S16LE
  match:
    usb_vendor_id: "{_MOCK_VID}"
    usb_product_id: "{_MOCK_PID}"
    alsa_name_contains: "UltraMic"
processing:
  gain_db: 0.0
  chunk_size: 4096
stream:
  raw_enabled: true
  processed_enabled: true
  live_stream_enabled: false
  segment_duration_s: 15
""",
        encoding="utf-8",
    )
    return profiles_dir


# -----------------------------------------------------------------------
# Full Flow Test
# -----------------------------------------------------------------------


class TestEvaluatorDBScoped:
    """Verify DeviceStateEvaluator produces correct specs from real DB data."""

    async def test_evaluator_returns_spec_for_enrolled_device(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Enrolled device in DB → evaluator returns a Tier2ServiceSpec."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # 1) Seed a profile
        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir(exist_ok=True)
        (profiles_dir / "spawn_test.yml").write_text(
            """
schema_version: "1.0"
slug: spawn_test
name: Spawn Test Profile
description: For recorder spawn integration test.
audio:
  sample_rate: 48000
  channels: 1
  format: S16LE
processing:
  gain_db: 0.0
  chunk_size: 4096
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

        # 2) Create a device (enrolled + online)
        from silvasonic.controller.device_scanner import DeviceInfo

        device_info = DeviceInfo(
            alsa_card_index=50,
            alsa_name="SpawnTestMic",
            alsa_device="hw:50,0",
            usb_vendor_id="cafe",
            usb_product_id="babe",
            usb_serial="SPAWN-001",
        )
        async with session_factory() as session:
            await upsert_device(
                device_info,
                session,
                profile_slug="spawn_test",
                enrollment_status="enrolled",
            )
            await session.commit()

        # 3) Run evaluator
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        await engine.dispose()

        # Should produce exactly one spec for our device
        assert len(specs) >= 1
        our_spec = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == "cafe-babe-SPAWN-001"
        ]
        assert len(our_spec) == 1
        spec = our_spec[0]
        assert spec.name == "silvasonic-recorder-spawn-test-001"
        assert spec.environment["SILVASONIC_RECORDER_PROFILE_SLUG"] == "spawn_test"

    async def test_evaluator_skips_offline_device(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Offline device in DB → evaluator does NOT return a spec."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Seed profile
        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir(exist_ok=True)
        (profiles_dir / "offline_test.yml").write_text(
            """
schema_version: "1.0"
slug: offline_test
name: Offline Test Profile
description: For offline device test.
audio:
  sample_rate: 48000
  channels: 1
  format: S16LE
processing:
  gain_db: 0.0
  chunk_size: 4096
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

        # Create enrolled device, then set offline
        from silvasonic.controller.device_scanner import DeviceInfo

        device_info = DeviceInfo(
            alsa_card_index=51,
            alsa_name="OfflineMic",
            alsa_device="hw:51,0",
            usb_vendor_id="dead",
            usb_product_id="face",
            usb_serial="OFFLINE-001",
        )
        async with session_factory() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug="offline_test",
                enrollment_status="enrolled",
            )
            # Manually set offline
            device.status = "offline"
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        await engine.dispose()

        # Offline device should NOT produce a spec
        offline_specs = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == "dead-face-OFFLINE-001"
        ]
        assert len(offline_specs) == 0


class TestRecorderSpawnFlow:
    """Full integration: scan → match → DB upsert → evaluate → container start."""

    async def test_usb_mic_detected_and_recorder_spawned(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """A USB mic detection results in a recorder container being started.

        Steps:
        1. Seed a matching profile into DB
        2. Scan mocked /proc/asound/cards → DeviceInfo
        3. Match device against profiles → auto-enroll
        4. Upsert device into DB (online + enrolled)
        5. Evaluate desired state from DB → Tier2ServiceSpec
        6. Reconcile → ContainerManager.start() called with correct spec
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # -- Step 1: Seed profile into real DB --
        from silvasonic.controller.seeder import ConfigSeeder, ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)

        # Seed system config with auto_enrollment=true
        defaults_yml = tmp_path / "defaults.yml"
        defaults_yml.write_text(
            """
system:
  station_name: "Integration Test Station"
  auto_enrollment: true

auth:
  default_username: "admin"
  default_password: "testpass"
""",
            encoding="utf-8",
        )

        async with session_factory() as session:
            await ConfigSeeder(defaults_path=defaults_yml).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # -- Step 2: Scan mocked ALSA cards --
        cards_file = tmp_path / "cards"
        cards_file.write_text(MOCK_ASOUND_CARDS)
        scanner = DeviceScanner(cards_path=cards_file)

        with patch(
            "silvasonic.controller.device_scanner._get_usb_info_for_card",
            return_value=_mock_usb_info("FLOW-TEST-001"),
        ):
            devices = scanner.scan_all()

        assert len(devices) == 1, f"Expected 1 USB device, got {len(devices)}"
        device_info = devices[0]
        assert device_info.alsa_name == _MOCK_ALSA_NAME
        assert device_info.stable_device_id == _device_id("FLOW-TEST-001")

        # -- Step 3: Match against profiles in DB --
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(device_info, session)

        assert match_result.score == 100, (
            f"Expected exact USB match, got score={match_result.score}"
        )
        assert match_result.profile_slug == _MOCK_PROFILE_SLUG
        assert match_result.auto_enroll is True

        # -- Step 4: Upsert device into real DB --
        async with session_factory() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled" if match_result.auto_enroll else "pending",
            )
            await session.commit()
            # Capture values before session closes
            device_name = device.name
            device_status = device.status
            device_enrollment = device.enrollment_status
            device_profile = device.profile_slug

        assert device_name == _device_id("FLOW-TEST-001")
        assert device_status == "online"
        assert device_enrollment == "enrolled"
        assert device_profile == _MOCK_PROFILE_SLUG

        # -- Step 5: Evaluate desired state from DB --
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            all_specs = await evaluator.evaluate(session)

        specs = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("FLOW-TEST-001")
        ]
        assert len(specs) == 1, f"Expected 1 spec for FLOW-TEST-001, got {len(specs)}"
        spec = specs[0]
        assert isinstance(spec, Tier2ServiceSpec)
        assert spec.name == "silvasonic-recorder-ultramic-384k-001"
        assert spec.environment["SILVASONIC_RECORDER_PROFILE_SLUG"] == _MOCK_PROFILE_SLUG
        assert spec.image == "localhost/silvasonic_recorder:latest"
        assert spec.oom_score_adj == -999  # Protected (ADR-0020)

        # -- Step 6: Reconcile with mock Podman --
        mock_podman = MagicMock()
        mock_podman.is_connected = True
        mock_podman.list_managed_containers.return_value = []  # No running containers

        # Mock containers.get to raise NotFound (container doesn't exist yet)
        from podman.errors import NotFound

        mock_podman.containers.get.side_effect = NotFound("silvasonic-recorder-ultramic-384k-001")

        # Mock containers.run to return a fake container
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_container.name = "silvasonic-recorder-ultramic-384k-001"
        mock_container.status = "running"
        mock_container.labels = spec.labels
        mock_podman.containers.run.return_value = mock_container

        mgr = ContainerManager(mock_podman)
        actual = mgr.list_managed()

        # Reconcile: we pass the filtered specs (1 spec), actual 0 → should start 1
        mgr.sync_state(desired=specs, actual=actual)

        # Verify the container was started with correct parameters
        mock_podman.containers.run.assert_called_once()
        call_kwargs = mock_podman.containers.run.call_args
        assert call_kwargs.kwargs["image"] == "localhost/silvasonic_recorder:latest"
        assert call_kwargs.kwargs["name"] == "silvasonic-recorder-ultramic-384k-001"
        assert (
            call_kwargs.kwargs["environment"]["SILVASONIC_RECORDER_PROFILE_SLUG"]
            == _MOCK_PROFILE_SLUG
        )
        assert call_kwargs.kwargs["labels"]["io.silvasonic.owner"] == "controller"
        assert call_kwargs.kwargs["labels"]["io.silvasonic.device_id"] == _device_id(
            "FLOW-TEST-001"
        )

        await engine.dispose()

    async def test_offline_device_stops_recorder(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """When a device goes offline, reconciliation stops its recorder.

        Steps:
        1. Seed profile + create enrolled online device
        2. Set device offline in DB
        3. Evaluate → empty specs
        4. Reconcile with one running container → stop called
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Seed profile
        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with session_factory() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Create device, then set it offline
        device_info = _make_device("OFFLINE-FLOW")

        async with session_factory() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            device.status = "offline"  # Simulate unplug
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            all_specs = await evaluator.evaluate(session)

        specs = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("OFFLINE-FLOW")
        ]
        assert len(specs) == 0, "Offline device should not produce a spec"

        # Reconcile: 0 desired (for this device), 1 actual → stop called
        mock_podman = MagicMock()
        mock_podman.is_connected = True

        mock_container_obj = MagicMock()
        mock_podman.containers.get.return_value = mock_container_obj

        mgr = ContainerManager(mock_podman)

        from typing import Any

        fake_running: list[dict[str, Any]] = [
            {
                "name": "silvasonic-recorder-ultramic-384k-flow",
                "status": "running",
                "labels": {"io.silvasonic.owner": "controller"},
            }
        ]

        mgr.sync_state(desired=all_specs, actual=fake_running)

        # The orphaned container should have been stopped (via stop_and_remove).
        # Note: stop() may be called multiple times because the shared mock_podman
        # makes all containers.get() calls return the same mock object, and
        # start() also calls stop_and_remove() for containers it considers "exited".
        mock_container_obj.stop.assert_called()

        await engine.dispose()


# -----------------------------------------------------------------------
# Lifecycle Edge Cases (US-C07, US-C01, US-C02, US-C04, US-R05)
# -----------------------------------------------------------------------


class TestRecorderLifecycleEdgeCases:
    """Integration tests for device-state edge cases (real DB, mock Podman)."""

    async def test_disabled_device_produces_no_spec(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Disabled device → evaluator returns no spec (US-C07)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        device_info = _make_device("DISABLED-001", card_index=10)
        async with sf() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            device.enabled = False  # Emergency stop (US-C07)
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s
            for s in specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("DISABLED-001")
        ]
        assert len(matching) == 0, "Disabled device must not produce a spec"
        await engine.dispose()

    async def test_unenrolled_device_produces_no_spec(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Pending (unenrolled) device → evaluator returns no spec (US-C07)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        device_info = _make_device("PENDING-001", card_index=11)
        async with sf() as session:
            await upsert_device(
                device_info,
                session,
                profile_slug=None,
                enrollment_status="pending",
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == _device_id("PENDING-001")
        ]
        assert len(matching) == 0, "Pending device must not produce a spec"
        await engine.dispose()

    async def test_replug_reactivates_same_device(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Re-plugging a mic re-activates the same device (US-C01§3)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        device_info = _make_device("REPLUG-001", card_index=12)

        # First insert: online + enrolled
        async with sf() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            original_name = device.name
            await session.commit()

        # Simulate unplug: set offline
        from silvasonic.core.database.models.system import Device

        async with sf() as session:
            device_row = await session.get(Device, original_name)
            assert device_row is not None
            device_row.status = "offline"
            await session.commit()

        # Replug: upsert same device again
        async with sf() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            await session.commit()
            replug_name = device.name
            replug_status = device.status

        assert replug_name == original_name, "Same serial → same device row"
        assert replug_status == "online", "Re-plugged device must be online"

        # Evaluate → should produce a spec again
        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == _device_id("REPLUG-001")
        ]
        assert len(matching) == 1, "Re-plugged device must produce exactly 1 spec"
        await engine.dispose()

    async def test_auto_enrollment_disabled_keeps_pending(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """With auto_enrollment=false, new devices stay pending (US-C01§4)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper
        from silvasonic.core.database.models.system import SystemConfig

        profiles_dir = _seed_matching_profile(tmp_path)

        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            # Directly set auto_enrollment=false (ConfigSeeder skips existing keys)
            existing = await session.get(SystemConfig, "system")
            if existing is not None:
                val = dict(existing.value) if existing.value else {}
                val["auto_enrollment"] = False
                existing.value = val
            else:
                session.add(
                    SystemConfig(
                        key="system",
                        value={"station_name": "Test", "auto_enrollment": False},
                    )
                )
            await session.commit()

        # Scan a matching device
        device_info = _make_device("NOENROLL-001", card_index=13)

        # Match profiles
        matcher = ProfileMatcher()
        async with sf() as session:
            match_result = await matcher.match(device_info, session)

        # Match should be found (score=100) but auto_enroll should be False
        assert match_result.score == 100
        assert match_result.auto_enroll is False, (
            "auto_enrollment=false should set auto_enroll=False"
        )

        # Upsert as pending (since auto_enroll=False)
        async with sf() as session:
            device = await upsert_device(
                device_info,
                session,
                profile_slug=None,
                enrollment_status="pending",
            )
            assert device.enrollment_status == "pending"
            await session.commit()

        # Evaluator should produce no spec
        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s
            for s in specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("NOENROLL-001")
        ]
        assert len(matching) == 0, "Pending device must not produce a spec"

        # Restore auto_enrollment=True to avoid polluting shared DB for other tests
        async with sf() as session:
            cfg = await session.get(SystemConfig, "system")
            if cfg is not None:
                val = dict(cfg.value) if cfg.value else {}
                val["auto_enrollment"] = True
                cfg.value = val
                await session.commit()

        await engine.dispose()


class TestRecorderSpecIntegrity:
    """Integration tests for spec content correctness (real DB)."""

    async def test_spec_contains_resource_limits(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Resource limits (ADR-0020) are present in spec (US-C04)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        device_info = _make_device("RESLIM-001", card_index=20)
        async with sf() as session:
            await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == _device_id("RESLIM-001")
        ]
        assert len(matching) == 1
        spec = matching[0]

        # ADR-0020: Resource limits must be present and correct
        assert spec.memory_limit == "512m", "Default memory limit must be 512m"
        assert spec.cpu_limit == 1.0, "Default CPU limit must be 1.0"
        assert spec.oom_score_adj == -999, "Recorder OOM score must be -999 (protected)"

        # Verify these translate to correct podman kwargs
        mock_podman = MagicMock()
        mock_podman.is_connected = True
        from podman.errors import NotFound

        mock_podman.containers.get.side_effect = NotFound("test")
        mock_container = MagicMock()
        mock_container.id = "res123"
        mock_container.name = spec.name
        mock_container.status = "running"
        mock_container.labels = spec.labels
        mock_podman.containers.run.return_value = mock_container

        mgr = ContainerManager(mock_podman)
        mgr.start(spec)

        call_kwargs = mock_podman.containers.run.call_args.kwargs
        assert call_kwargs["mem_limit"] == "512m"
        assert call_kwargs["cpu_quota"] == 100_000  # 1.0 * 100_000
        assert call_kwargs["oom_score_adj"] == -999

        await engine.dispose()

    async def test_spec_contains_restart_policy(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Restart policy on-failure/5 is set in spec (US-C02)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        device_info = _make_device("RESTART-001", card_index=21)
        async with sf() as session:
            await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == _device_id("RESTART-001")
        ]
        assert len(matching) == 1
        spec = matching[0]

        # ADR-0013: Restart policy
        assert spec.restart_policy.name == "on-failure"
        assert spec.restart_policy.max_retry_count == 5

        # Verify in podman kwargs
        mock_podman = MagicMock()
        mock_podman.is_connected = True
        from podman.errors import NotFound

        mock_podman.containers.get.side_effect = NotFound("test")
        mock_container = MagicMock()
        mock_container.id = "rst123"
        mock_container.name = spec.name
        mock_container.status = "running"
        mock_container.labels = spec.labels
        mock_podman.containers.run.return_value = mock_container

        mgr = ContainerManager(mock_podman)
        mgr.start(spec)

        call_kwargs = mock_podman.containers.run.call_args.kwargs
        assert call_kwargs["restart_policy"] == {
            "Name": "on-failure",
            "MaximumRetryCount": 5,
        }

        await engine.dispose()

    async def test_container_name_matches_workspace_dir(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Container name and workspace directory use same human-readable name."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        device_info = _make_device("NAMECHK-001", card_index=22)
        async with sf() as session:
            await upsert_device(
                device_info,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s for s in specs if s.labels.get("io.silvasonic.device_id") == _device_id("NAMECHK-001")
        ]
        assert len(matching) == 1
        spec = matching[0]

        # Container name is human-readable
        assert spec.name.startswith("silvasonic-recorder-")
        readable_part = spec.name.removeprefix("silvasonic-recorder-")

        # Workspace mount source must end with the same readable part
        assert len(spec.mounts) >= 1
        workspace_mount = spec.mounts[0]
        workspace_dir = Path(workspace_mount.source).name
        assert workspace_dir == readable_part, (
            f"Workspace dir '{workspace_dir}' must match container suffix '{readable_part}'"
        )

        # Must NOT contain the raw device_id
        assert "NAMECHK-001" not in workspace_dir
        assert f"{_MOCK_VID}-{_MOCK_PID}" not in workspace_dir

        await engine.dispose()

    async def test_two_mics_produce_two_independent_specs(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Two enrolled mics → two distinct specs with different names (US-R05)."""
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Two identical-model mics with different serial numbers
        mic_a = _make_device("MULTI-AAA", card_index=30)
        mic_b = _make_device("MULTI-BBB", card_index=31)

        async with sf() as session:
            await upsert_device(
                mic_a, session, profile_slug=_MOCK_PROFILE_SLUG, enrollment_status="enrolled"
            )
            await upsert_device(
                mic_b, session, profile_slug=_MOCK_PROFILE_SLUG, enrollment_status="enrolled"
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            all_specs = await evaluator.evaluate(session)

        specs_a = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("MULTI-AAA")
        ]
        specs_b = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("MULTI-BBB")
        ]

        assert len(specs_a) == 1, "Mic A must produce exactly 1 spec"
        assert len(specs_b) == 1, "Mic B must produce exactly 1 spec"

        # Names must be different
        assert specs_a[0].name != specs_b[0].name, (
            f"Two mics must have different container names: {specs_a[0].name} vs {specs_b[0].name}"
        )

        # Workspace dirs must be different
        ws_a = Path(specs_a[0].mounts[0].source).name
        ws_b = Path(specs_b[0].mounts[0].source).name
        assert ws_a != ws_b, f"Two mics must have different workspace dirs: {ws_a} vs {ws_b}"

        # Both must share the same profile slug prefix
        assert "ultramic-384k" in specs_a[0].name
        assert "ultramic-384k" in specs_b[0].name

        await engine.dispose()


# -----------------------------------------------------------------------
# Generic USB Fallback (v0.4.0 Phase 3, US-C10)
# -----------------------------------------------------------------------


class TestGenericUsbFallback:
    """Integration: unknown device → generic_usb fallback → recorder spec."""

    async def test_unknown_device_gets_generic_fallback_and_spawns(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Unknown USB device (no VID/PID match) auto-enrolls with generic_usb.

        Steps:
        1. Seed generic_usb profile + one known profile (no match for our device)
        2. Match unknown device → score 0 → fallback assigns generic_usb
        3. Upsert device as enrolled with generic_usb
        4. Evaluate → produces a Tier2ServiceSpec with generic_usb config
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ConfigSeeder, ProfileBootstrapper

        # Seed generic_usb profile (from real YAML file) + known profile
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir(exist_ok=True)

        # Copy the real generic_usb.yml
        import shutil

        from silvasonic.controller.seeder import _find_service_root

        real_profiles = _find_service_root() / "config" / "profiles"
        shutil.copy(real_profiles / "generic_usb.yml", profiles_dir / "generic_usb.yml")

        # Also seed a known profile that does NOT match our device
        (profiles_dir / "known_mic.yml").write_text(
            """
schema_version: "1.0"
slug: known_mic
name: Known Microphone
description: A known mic that won't match our unknown device.
audio:
  sample_rate: 96000
  channels: 2
  format: S24LE
  match:
    usb_vendor_id: "ffff"
    usb_product_id: "ffff"
processing:
  gain_db: 6.0
  chunk_size: 8192
stream:
  raw_enabled: true
  processed_enabled: true
  live_stream_enabled: false
  segment_duration_s: 20
""",
            encoding="utf-8",
        )

        # Seed system config with auto_enrollment=true
        defaults_yml = tmp_path / "defaults.yml"
        defaults_yml.write_text(
            """
system:
  station_name: "Fallback Test Station"
  auto_enrollment: true
""",
            encoding="utf-8",
        )

        async with sf() as session:
            await ConfigSeeder(defaults_path=defaults_yml).seed(session)
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Step 2: Match an unknown device (VID/PID that doesn't match anything)
        unknown_device = DeviceInfo(
            alsa_card_index=99,
            alsa_name="Unknown USB Audio",
            alsa_device="hw:99,0",
            usb_vendor_id="1234",
            usb_product_id="5678",
            usb_serial="UNKNOWN-001",
        )

        matcher = ProfileMatcher()
        async with sf() as session:
            match_result = await matcher.match(unknown_device, session)

        # Score 0, but fallback to generic_usb
        assert match_result.score == 0, f"Expected score 0, got {match_result.score}"
        assert match_result.profile_slug == "generic_usb", (
            f"Expected generic_usb fallback, got {match_result.profile_slug}"
        )
        assert match_result.auto_enroll is True

        # Step 3: Upsert as enrolled with generic_usb
        async with sf() as session:
            device = await upsert_device(
                unknown_device,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled",
            )
            await session.commit()
            device_name = device.name
            device_profile = device.profile_slug

        assert device_profile == "generic_usb"
        assert device_name == "1234-5678-UNKNOWN-001"

        # Step 4: Evaluate → should produce a spec with generic_usb config
        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            all_specs = await evaluator.evaluate(session)

        matching = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == "1234-5678-UNKNOWN-001"
        ]
        assert len(matching) == 1, f"Expected 1 spec, got {len(matching)}"
        spec = matching[0]

        # Verify the spec uses generic_usb profile settings
        assert isinstance(spec, Tier2ServiceSpec)
        assert spec.environment["SILVASONIC_RECORDER_PROFILE_SLUG"] == "generic_usb"
        assert "SILVASONIC_RECORDER_CONFIG_JSON" in spec.environment

        # Verify the injected config JSON contains 48kHz/1ch/S16LE
        import json

        config = json.loads(spec.environment["SILVASONIC_RECORDER_CONFIG_JSON"])
        assert config["audio"]["sample_rate"] == 48000
        assert config["audio"]["channels"] == 1
        assert config["audio"]["format"] == "S16LE"
        assert config["processing"]["gain_db"] == 0.0

        await engine.dispose()


# -----------------------------------------------------------------------
# Container Name Suffix Uniqueness (US-R05, ADR-0013)
# -----------------------------------------------------------------------


class TestContainerNameSuffixUniqueness:
    """Verify container names are collision-free when devices share a profile.

    Two devices with the SAME profile slug but different USB serials must
    produce container names that differ only by the _short_suffix() (last 4
    hex chars of the serial).  This test validates the complete naming
    pipeline from device upsert → evaluate → spec generation.
    """

    async def test_suffix_derived_from_serial_last_4_chars(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Two mics (same profile, different serials) get suffix from serial[-4:].

        Steps:
        1. Seed profile matching both devices.
        2. Upsert 2 devices with serials 'SERIAL-AAA001' and 'SERIAL-BBB002'.
        3. Evaluate → 2 specs.
        4. Verify names are 'silvasonic-recorder-ultramic-384k-a001' and '-b002'.
        5. Verify workspace dirs match the unique suffix part.
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Two devices with same VID/PID/profile but different serials
        mic_a = _make_device("SERIAL-AAA001", card_index=40)
        mic_b = _make_device("SERIAL-BBB002", card_index=41)

        async with sf() as session:
            await upsert_device(
                mic_a, session, profile_slug=_MOCK_PROFILE_SLUG, enrollment_status="enrolled"
            )
            await upsert_device(
                mic_b, session, profile_slug=_MOCK_PROFILE_SLUG, enrollment_status="enrolled"
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            all_specs = await evaluator.evaluate(session)

        specs_a = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("SERIAL-AAA001")
        ]
        specs_b = [
            s
            for s in all_specs
            if s.labels.get("io.silvasonic.device_id") == _device_id("SERIAL-BBB002")
        ]

        assert len(specs_a) == 1
        assert len(specs_b) == 1

        name_a = specs_a[0].name
        name_b = specs_b[0].name

        # Names must differ
        assert name_a != name_b, f"Name collision: {name_a} == {name_b}"

        # Both should contain the profile slug (normalized to hyphens)
        assert "ultramic-384k" in name_a, f"Missing profile slug in name: {name_a}"
        assert "ultramic-384k" in name_b, f"Missing profile slug in name: {name_b}"

        # Suffix should be last 4 chars of serial (lowercased)
        assert name_a.endswith("a001"), f"Expected suffix 'a001', got name: {name_a}"
        assert name_b.endswith("b002"), f"Expected suffix 'b002', got name: {name_b}"

        # Verify Podman-safe format: only lowercase + hyphens + digits
        import re

        for name in [name_a, name_b]:
            assert re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", name), (
                f"Name '{name}' is not Podman-safe (only lowercase, digits, hyphens allowed)"
            )

        # Workspace dirs must also differ and match the container suffix
        ws_a = Path(specs_a[0].mounts[0].source).name
        ws_b = Path(specs_b[0].mounts[0].source).name
        assert ws_a != ws_b, f"Workspace collision: {ws_a} == {ws_b}"

        # Workspace dir = container name minus 'silvasonic-recorder-' prefix
        assert ws_a == name_a.removeprefix("silvasonic-recorder-"), (
            f"Workspace '{ws_a}' must match container suffix"
        )
        assert ws_b == name_b.removeprefix("silvasonic-recorder-"), (
            f"Workspace '{ws_b}' must match container suffix"
        )

        await engine.dispose()

    async def test_suffix_falls_back_to_bus_path_without_serial(
        self,
        tmp_path: Path,
        postgres_container: PostgresContainer,
    ) -> None:
        """Device without USB serial uses bus_path as suffix fallback.

        Verifies _short_suffix() fallback chain:
        serial → bus_path → alsa_card_index.
        """
        url = build_postgres_url(postgres_container)
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        from silvasonic.controller.seeder import ProfileBootstrapper

        profiles_dir = _seed_matching_profile(tmp_path)
        async with sf() as session:
            await ProfileBootstrapper(profiles_dir=profiles_dir).seed(session)
            await session.commit()

        # Device without serial — uses bus_path "1-3.2" → suffix "p1d3"
        device_no_serial = DeviceInfo(
            alsa_card_index=50,
            alsa_name=_MOCK_ALSA_NAME,
            alsa_device="hw:50,0",
            usb_vendor_id=_MOCK_VID,
            usb_product_id=_MOCK_PID,
            usb_serial=None,
            usb_bus_path="1-3.2",
        )

        async with sf() as session:
            await upsert_device(
                device_no_serial,
                session,
                profile_slug=_MOCK_PROFILE_SLUG,
                enrollment_status="enrolled",
            )
            await session.commit()

        evaluator = DeviceStateEvaluator()
        async with sf() as session:
            all_specs = await evaluator.evaluate(session)

        stable_id = device_no_serial.stable_device_id
        matching = [s for s in all_specs if s.labels.get("io.silvasonic.device_id") == stable_id]
        assert len(matching) == 1
        spec = matching[0]

        # Suffix should be bus_path based: "1-3.2" → "p1d3"
        assert spec.name.endswith("p1d3"), f"Expected bus_path suffix 'p1d3', got name: {spec.name}"

        # Name must still be valid for Podman
        assert spec.name.startswith("silvasonic-recorder-")

        await engine.dispose()
