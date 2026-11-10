"""Integration tests for SystemWorkerEvaluator."""

import pytest
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.worker_evaluator import SystemWorkerEvaluator
from silvasonic.core.database.models.system import Module
from silvasonic.core.database.session import get_session
from sqlalchemy import delete

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def clear_modules() -> None:
    """Clear modules table before each test to ensure isolation."""
    # In integration tests we usually use standard conftest fixtures,
    # but manually clearing specific tables is also fine
    async with get_session() as session:
        await session.execute(delete(Module))
        await session.commit()


async def test_evaluator_ignores_disabled_modules() -> None:
    """Evaluator skips rows where enabled=False."""
    async with get_session() as session:
        session.add(Module(id="birdnet", enabled=False))
        await session.commit()

        evaluator = SystemWorkerEvaluator()
        specs = await evaluator.evaluate(session)

    assert len(specs) == 0


async def test_evaluator_builds_spec_for_enabled_registry_worker() -> None:
    """Evaluator builds a Tier2ServiceSpec for an enabled worker present in registry."""
    async with get_session() as session:
        session.add(Module(id="birdnet", enabled=True))
        await session.commit()

        evaluator = SystemWorkerEvaluator()
        specs = await evaluator.evaluate(session)

    assert len(specs) == 1
    spec = specs[0]
    assert isinstance(spec, Tier2ServiceSpec)
    assert spec.name == "silvasonic-birdnet"
    assert spec.image == "localhost/silvasonic_birdnet:latest"
    assert spec.memory_limit == "512m"
    assert spec.cpu_limit == 1.0
    assert spec.oom_score_adj == 500

    # Assert Zero-Trust mounts mapping
    mount_targets = [m.target for m in spec.mounts]
    assert "/data/recorder" in mount_targets
    assert "/data/birdnet" in mount_targets

    # Assert Recorder mount is read-only
    recorder_mount = next(m for m in spec.mounts if m.target == "/data/recorder")
    assert recorder_mount.read_only is True


async def test_evaluator_ignores_unknown_enabled_modules() -> None:
    """Evaluator ignores enabled modules not present in the SYSTEM_WORKERS registry."""
    async with get_session() as session:
        session.add(Module(id="unknown_worker", enabled=True))
        await session.commit()

        evaluator = SystemWorkerEvaluator()
        specs = await evaluator.evaluate(session)

    assert len(specs) == 0


async def test_evaluator_ignores_cloud_sync_module() -> None:
    """A switched-on cloud_sync module is run by the Processor, not orchestrated.

    Only the Tier 2 singletons of SYSTEM_WORKERS become container specs.
    """
    async with get_session() as session:
        session.add(Module(id="cloud_sync", enabled=True))
        session.add(Module(id="birdnet", enabled=True))
        await session.commit()

        evaluator = SystemWorkerEvaluator()
        specs = await evaluator.evaluate(session)

    assert [spec.name for spec in specs] == ["silvasonic-birdnet"]
