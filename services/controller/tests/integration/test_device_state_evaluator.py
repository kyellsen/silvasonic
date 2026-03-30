"""Integration test for DeviceStateEvaluator — Golden Path.

Verifies that the ORM query mapping within DeviceStateEvaluator correctly
constructs Tier2ServiceSpecs when valid Profiles and Devices exist in the
real database. This replaces brittle SQLAlchemy Mock chaining.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silvasonic.controller.device_repository import upsert_device
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.reconciler import DeviceStateEvaluator
from silvasonic.controller.seeder import ProfileBootstrapper
from silvasonic.test_utils.helpers import build_postgres_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = [
    pytest.mark.integration,
]


@pytest.mark.asyncio
async def test_evaluate_golden_path_yields_spec(
    tmp_path: Path,
    postgres_container: PostgresContainer,
) -> None:
    """Evaluator generates a valid Tier2ServiceSpec for an online, enrolled device."""
    url = build_postgres_url(postgres_container)
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Seed a valid SystemProfile via Bootstrapper
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "test_eval_profile.yml").write_text(
        """
schema_version: "1.0"
slug: eval_profile
name: Evaluation Profile
description: Integration test profile
audio:
  sample_rate: 48000
  channels: 1
  format: S16LE
processing:
  gain_db: 0.0
stream:
  raw_enabled: true
  processed_enabled: true
  segment_duration_s: 15
""",
        encoding="utf-8",
    )
    bootstrapper = ProfileBootstrapper(profiles_dir=profiles_dir)

    async with session_factory() as session:
        await bootstrapper.seed(session)
        await session.commit()

    # 2. Insert a valid Device bound to the Profile
    device_info = DeviceInfo(
        alsa_card_index=1,
        alsa_name="EvalMic",
        alsa_device="hw:1,0",
        usb_vendor_id="aaaa",
        usb_product_id="bbbb",
        usb_serial="EVAL-001",
    )

    async with session_factory() as session:
        # Upsert with profile & explicit enrolled status
        await upsert_device(
            device_info,
            session,
            profile_slug="eval_profile",
            enrollment_status="enrolled",
        )
        await session.commit()

    # 3. Test the DeviceStateEvaluator against the real DB
    evaluator = DeviceStateEvaluator()

    async with session_factory() as session:
        specs = await evaluator.evaluate(session)

    await engine.dispose()

    assert len(specs) == 1
    # Verify standard container naming
    spec = specs[0]
    assert spec.name.startswith("silvasonic-recorder-eval-profile")
    assert "silvasonic" in spec.image

    # Confirm volatile config propagation via environment dictionary
    assert "SILVASONIC_RECORDER_DEVICE" in spec.environment
    assert spec.environment["SILVASONIC_RECORDER_DEVICE"] == "hw:1,0"

    # Check workspace bindings
    assert len(spec.mounts) > 0
