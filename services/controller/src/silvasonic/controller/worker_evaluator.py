"""System Worker Evaluator for Tier 2 singleton containers (ADR-0029)."""

from __future__ import annotations

import structlog
from silvasonic.controller.container_spec import Tier2ServiceSpec, build_worker_spec
from silvasonic.controller.worker_registry import SYSTEM_WORKERS
from silvasonic.core.database.models.system import Module
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


class SystemWorkerEvaluator:
    """Evaluate which singleton background workers should be running.

    Queries the ``modules`` table for switched-on modules (enabled=True)
    and cross-references with the static ``SYSTEM_WORKERS`` registry to
    generate operational container specs. Modules that no Tier 2 worker
    implements (e.g. ``cloud_sync``, run by the Processor) are ignored.
    """

    async def evaluate(self, session: AsyncSession) -> list[Tier2ServiceSpec]:
        """Query enabled modules and build Tier2ServiceSpecs.

        Returns:
            List of specs for Tier 2 background worker containers.
        """
        stmt = select(Module.id).where(Module.enabled.is_(True))
        result = await session.execute(stmt)
        enabled_ids = set(result.scalars().all())

        specs: list[Tier2ServiceSpec] = []

        for worker in SYSTEM_WORKERS:
            if worker.name in enabled_ids:
                try:
                    spec = build_worker_spec(worker)
                    specs.append(spec)
                except Exception:
                    log.exception(
                        "worker_evaluator.spec_build_failed",
                        worker=worker.name,
                    )

        log.debug("worker_evaluator.evaluated", eligible_count=len(specs))
        return specs
