"""State reconciliation for Tier 2 containers (ADR-0017).

Implements the Kubernetes-inspired reconciliation pattern:

1. **MicrophoneStateEvaluator** — determines which microphones should have Recorders.
2. **ReconciliationLoop** — periodic async task that compares desired vs. actual.

The Controller reads desired state from the database (``microphones`` + ``microphone_profiles``)
and reconciles against actual state from Podman (running containers queried by label).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, NoReturn

import structlog
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    Tier2ServiceSpec,
    build_recorder_spec,
    generate_workspace_name,
)
from silvasonic.controller.device_scanner import DeviceScanner
from silvasonic.controller.microphone_repository import upsert_microphone
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.worker_evaluator import SystemWorkerEvaluator
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import Microphone
from silvasonic.core.database.session import get_session
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from silvasonic.controller.controller_stats import ControllerStats
    from silvasonic.controller.device_scanner import DeviceInfo

log = structlog.get_logger()


class MicrophoneStateEvaluator:
    """Evaluate which microphones should have running Recorders.

    A microphone is eligible for recording when ALL conditions are met
    (Controller README §Microphone State Evaluation):

    - ``connection_state == "connected"``
    - ``enabled == True``
    - ``enrollment_state == "enrolled"``
    - ``profile_slug IS NOT NULL``
    """

    def __init__(self) -> None:
        """Initialize with empty rate-limiting set for missing profiles."""
        self._warned_profiles: set[str] = set()

    async def evaluate(self, session: AsyncSession) -> list[Tier2ServiceSpec]:
        """Query eligible microphones and build Tier2ServiceSpecs.

        Returns:
            List of specs for Recorder containers that should be running.
        """
        stmt = select(Microphone).where(
            and_(
                Microphone.connection_state == "connected",
                Microphone.enabled.is_(True),
                Microphone.enrollment_state == "enrolled",
                Microphone.profile_slug.isnot(None),
            )
        )
        result = await session.execute(stmt)
        microphones = result.scalars().all()

        specs: list[Tier2ServiceSpec] = []

        for microphone in microphones:
            # Fetch the linked profile
            profile = await session.get(MicProfileDB, microphone.profile_slug)
            if profile is None:
                cache_key = f"{microphone.hardware_id}:{microphone.profile_slug}"
                if cache_key not in self._warned_profiles:
                    log.warning(
                        "reconciler.missing_profile",
                        hardware_id=microphone.hardware_id,
                        slug=microphone.profile_slug,
                    )
                    self._warned_profiles.add(cache_key)
                else:
                    log.debug(
                        "reconciler.missing_profile",
                        hardware_id=microphone.hardware_id,
                        slug=microphone.profile_slug,
                    )
                continue

            try:
                spec = build_recorder_spec(microphone, profile)
                specs.append(spec)
            except Exception:
                log.exception(
                    "reconciler.spec_build_failed",
                    hardware_id=microphone.hardware_id,
                )

        log.debug("reconciler.evaluated", eligible_count=len(specs))
        return specs


class ReconciliationLoop:
    """Periodic reconciliation loop comparing desired vs. actual state.

    Follows the State Reconciliation Pattern (ADR-0017, messaging_patterns.md §6).
    Can be triggered immediately via the ``trigger()`` method (from NudgeSubscriber).

    Each cycle:
    1. Rescan hardware (scan_all → match → upsert) to keep the DB in sync.
    2. Evaluate desired state from DB (connected + enrolled + profiled microphones).
    3. Compare desired vs. actual Podman containers → start/stop as needed.
    """

    def __init__(
        self,
        container_manager: ContainerManager,
        *,
        device_scanner: DeviceScanner | None = None,
        profile_matcher: ProfileMatcher | None = None,
        hardware_evaluator: MicrophoneStateEvaluator | None = None,
        sys_evaluator: SystemWorkerEvaluator | None = None,
        interval: float,
        grace_period_s: float = 3.0,
        redis_url: str | None = None,
        stale_timeout_s: float = 45.0,
    ) -> None:
        """Initialize with a ContainerManager and reconciliation interval."""
        self._manager = container_manager
        self._evaluator = hardware_evaluator or MicrophoneStateEvaluator()
        self._sys_evaluator = sys_evaluator or SystemWorkerEvaluator()
        self._scanner = device_scanner
        self._matcher = profile_matcher
        self._interval = interval
        self._grace_period_s = grace_period_s
        self._redis_url = redis_url
        self._stale_timeout_s = stale_timeout_s
        self._missing_microphones: dict[str, float] = {}
        # Container name → monotonic time it was first seen unhealthy
        self._unhealthy_since: dict[str, float] = {}
        # Container name → (heartbeat timestamp, monotonic time it was first read).
        # Freshness is measured on this clock, never against the wall clock:
        # an NTP step at boot moves `time.time()` but not the monotonic clock.
        self._heartbeat_seen: dict[str, tuple[float, float]] = {}
        self._trigger_event = asyncio.Event()
        self._stats: ControllerStats | None = None

    def set_stats(self, stats: ControllerStats) -> None:
        """Wire a ControllerStats instance for cycle tracking."""
        self._stats = stats

    def trigger(self) -> None:
        """Trigger an immediate reconciliation cycle (called by NudgeSubscriber)."""
        self._trigger_event.set()

    async def _run_cycle_once(self) -> None:
        """Execute exactly one reconciliation cycle and record stats.

        This method encapsulates a single execution of the reconcile logic and
        the bookkeeping of success/error statistics. It ensures that the stats
        contracts can be tested in isolation from the infinite run loop and
        its timeout mechanics.
        """
        try:
            await self._reconcile_once()
            if self._stats is not None:
                self._stats.record_reconcile_cycle()
        except Exception:
            log.exception("reconciler.cycle_failed")
            if self._stats is not None:
                self._stats.record_reconcile_error()

    async def run(self) -> NoReturn:
        """Run the reconciliation loop until cancelled.

        On each cycle:
        1. Rescan hardware and sync microphone state to DB.
        2. Query DB for desired state (eligible microphones).
        3. Query Podman for actual state (running containers).
        4. Reconcile: start missing, stop orphaned.
        """
        while True:
            await self._run_cycle_once()

            # Wait for interval OR immediate trigger
            try:
                await asyncio.wait_for(
                    self._trigger_event.wait(),
                    timeout=self._interval,
                )
            except TimeoutError:
                pass
            finally:
                self._trigger_event.clear()

    async def _reconcile_once(self) -> None:
        """Execute a single reconciliation cycle."""
        # Step 1: Rescan hardware → persist to DB
        if self._scanner is not None:
            await self._rescan_hardware()

        # Step 2: Evaluate desired state from DB
        desired: list[Tier2ServiceSpec] = []
        async with get_session() as session:
            try:
                hardware_specs = await self._evaluator.evaluate(session)
                desired.extend(hardware_specs)
            except Exception:
                log.exception("reconciler.hardware_evaluator_failed")

            try:
                worker_specs = await self._sys_evaluator.evaluate(session)
                desired.extend(worker_specs)
            except Exception:
                log.exception("reconciler.worker_evaluator_failed")

        # Step 3: Get actual running containers
        actual = await asyncio.to_thread(self._manager.list_managed)

        # Step 3.5: Health Evaluation (Issue 006)
        # Verify heartbeat freshness via Redis. A container whose heartbeat has
        # not changed for `stale_timeout_s` (measured on the Controller's
        # monotonic clock) is stopped at once and excluded from `actual`, so
        # `sync_state` recreates it. A missing or error heartbeat is tolerated
        # for `stale_timeout_s`: a container that is still booting has not
        # published yet, and Redis keeps no keys across a restart.
        if self._redis_url:
            from silvasonic.core.redis import get_redis_connection

            redis = await get_redis_connection(self._redis_url)
            if redis is not None:
                try:
                    actual = await self._filter_healthy(actual, redis)
                finally:
                    await redis.aclose()

        # Step 4: Track container actions in stats (before sync)
        if self._stats is not None:
            desired_specs = {spec.name: spec for spec in desired}
            actual_containers = {str(c.get("name", "")): c for c in actual}

            for name, spec in desired_specs.items():
                if name not in actual_containers:
                    self._stats.record_container_start(name)
                else:
                    # Check for config drift (re-create cycle)
                    c = actual_containers[name]
                    labels = c.get("labels", {})
                    actual_hash = ""
                    if isinstance(labels, dict):
                        actual_hash = labels.get("io.silvasonic.config_hash", "")

                    if actual_hash != spec.config_hash:
                        self._stats.record_container_stop(name)
                        self._stats.record_container_start(name)

            for name in actual_containers:
                if name not in desired_specs:
                    self._stats.record_container_stop(name)

        # Step 5: Reconcile desired vs. actual
        await asyncio.to_thread(
            self._manager.sync_state,
            desired,
            actual,
        )

    def _heartbeat_problem(
        self, name: str, raw: bytes | str | None, mono_now: float
    ) -> tuple[str | None, bool]:
        """Classify one heartbeat.

        A heartbeat is stale when its timestamp has not changed for
        ``stale_timeout_s`` on the Controller's monotonic clock. The
        timestamp only marks a new publish; comparing it with the wall clock
        would misfire when NTP steps the clock (Issue 002): a forward step
        made a live Recorder look stale, a backward step hid a hung one.

        Returns:
            ``(problem, immediate)``: ``problem`` is ``None`` for a healthy
            heartbeat, else the log event name; ``immediate`` is true when
            the container is to be removed without a grace period.
        """
        if not raw:
            return "reconciler.heartbeat_missing", False
        try:
            payload = json.loads(raw)
            timestamp = float(payload.get("timestamp", 0.0))
            status = payload.get("health", {}).get("status")
        except (ValueError, TypeError, AttributeError):
            return "reconciler.heartbeat_invalid", False
        seen = self._heartbeat_seen.get(name)
        if seen is None or seen[0] != timestamp:
            seen = self._heartbeat_seen[name] = (timestamp, mono_now)
        if mono_now - seen[1] > self._stale_timeout_s:
            return "reconciler.heartbeat_stale", True
        if status not in ("ok", "starting"):
            return "reconciler.heartbeat_reports_error", False
        return None, False

    async def _filter_healthy(
        self, actual: list[dict[str, object]], redis: Redis
    ) -> list[dict[str, object]]:
        """Stop unhealthy device containers and return the ones kept.

        Containers without a device label are not heartbeat-checked.
        """
        healthy: list[dict[str, object]] = []
        mono_now = time.monotonic()
        seen: set[str] = set()

        for c in actual:
            name = str(c.get("name", ""))
            labels = c.get("labels", {})
            device_id = labels.get("io.silvasonic.device_id") if isinstance(labels, dict) else None
            if not device_id:
                healthy.append(c)
                continue

            seen.add(name)
            raw = await redis.get(f"silvasonic:status:{device_id}")
            problem, immediate = self._heartbeat_problem(name, raw, mono_now)

            if problem is None:
                self._unhealthy_since.pop(name, None)
                healthy.append(c)
                continue

            first_seen = self._unhealthy_since.get(name)
            if first_seen is None:
                first_seen = self._unhealthy_since[name] = mono_now
                log.warning(problem, container=name, device_id=device_id)

            unhealthy_for = mono_now - first_seen
            if immediate or unhealthy_for >= self._stale_timeout_s:
                log.warning(
                    "reconciler.unhealthy_container_removed",
                    container=name,
                    device_id=device_id,
                    reason=problem,
                    unhealthy_for_s=round(unhealthy_for, 1),
                )
                await asyncio.to_thread(self._manager.stop_and_remove, name)
                self._unhealthy_since.pop(name, None)
                # Its successor starts with a fresh clock, even while Redis
                # still holds the old heartbeat
                self._heartbeat_seen.pop(name, None)
            else:
                healthy.append(c)

        # Forget containers that are gone
        for name in set(self._unhealthy_since) - seen:
            del self._unhealthy_since[name]
        for name in set(self._heartbeat_seen) - seen:
            del self._heartbeat_seen[name]
        return healthy

    async def scan_and_sync_devices(self) -> int:
        """Scan USB devices, match profiles, and sync the microphones to DB.

        Returns the number of devices found.  Reusable for both initial
        scan (during ``load_config``) and periodic rescans.
        """
        if self._scanner is None:
            return 0

        devices = await asyncio.to_thread(self._scanner.scan_all)

        async with get_session() as session:
            await self._upsert_detected_devices(devices, session)
            await self._mark_disconnected_microphones(
                {d.stable_device_id for d in devices},
                session,
            )
            await session.commit()

        return len(devices)

    async def _upsert_detected_devices(
        self,
        devices: list[DeviceInfo],
        session: AsyncSession,
    ) -> None:
        """Match profiles and upsert a microphone for each detected device."""
        # Pre-load all profiles once for the entire batch (M2 optimisation)
        from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB

        profiles: list[MicProfileDB] | None = None
        if self._matcher is not None:
            result = await session.execute(select(MicProfileDB))
            profiles = list(result.scalars().all())

        for device_info in devices:
            if self._matcher is not None:
                match_result = await self._matcher.match(
                    device_info,
                    session,
                    profiles=profiles,
                )
                profile_slug = match_result.profile_slug if match_result.auto_enroll else None
                enrollment = "enrolled" if match_result.auto_enroll else "pending"
            else:
                profile_slug = None
                enrollment = "pending"

            microphone = await upsert_microphone(
                device_info,
                session,
                profile_slug=profile_slug,
                enrollment_state=enrollment,
            )

            # Persist workspace_name for the Processor Indexer cross-service contract.
            # Only set when a profile is assigned (enrolled microphones get workspace dirs).
            if microphone.profile_slug:
                ws = generate_workspace_name(microphone.profile_slug, microphone)
                if microphone.workspace_name != ws:
                    microphone.workspace_name = ws

    async def _mark_disconnected_microphones(
        self,
        current_ids: set[str],
        session: AsyncSession,
    ) -> None:
        """Mark connected microphones as disconnected once no longer detected.

        ``current_ids`` are the hardware ids (Stable Device IDs) of the devices
        found by the latest scan.

        Uses a time-based grace period (hysteresis) to debounce temporary
        USB hotplugging or flappying.
        """
        now = time.monotonic()

        # Reset grace period for microphones that reappeared
        reappeared_ids = current_ids.intersection(self._missing_microphones)
        for device_id in reappeared_ids:
            del self._missing_microphones[device_id]
            log.info("reconciler.device_reappeared_in_grace", device_id=device_id)

        result = await session.execute(
            select(Microphone).where(Microphone.connection_state == "connected")
        )
        connected = result.scalars().all()
        connected_ids = {m.hardware_id for m in connected}

        # Clear orphaned state for microphones that are no longer connected in the DB
        # Use list(keys()) to prevent RuntimeError: dictionary changed size during iteration
        for device_id in list(self._missing_microphones.keys()):
            if device_id not in connected_ids and device_id not in current_ids:
                del self._missing_microphones[device_id]

        for microphone in connected:
            hw_id = microphone.hardware_id
            if hw_id not in current_ids:
                if hw_id not in self._missing_microphones:
                    # First time missing -> start grace period
                    self._missing_microphones[hw_id] = now
                    log.debug("reconciler.device_missing_start_grace", device_id=hw_id)
                elif now - self._missing_microphones[hw_id] >= self._grace_period_s:
                    # Grace period expired -> mark disconnected
                    microphone.connection_state = "disconnected"
                    del self._missing_microphones[hw_id]
                    log.info("reconciler.device_disconnected", device_id=hw_id)
                else:
                    # Missing but still within grace period -> do nothing
                    log.debug("reconciler.device_missing_in_grace", device_id=hw_id)

    async def _rescan_hardware(self) -> None:
        """Rescan USB audio devices and sync state to DB.

        Delegates to ``scan_and_sync_devices()`` and logs the result.
        """
        count = await self.scan_and_sync_devices()
        log.debug("reconciler.hardware_rescan", devices_found=count)
