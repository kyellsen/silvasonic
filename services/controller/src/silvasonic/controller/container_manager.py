"""Container lifecycle manager for Tier 2 services (ADR-0013).

Provides a high-level API for managing Tier 2 containers via the
``SilvasonicPodmanClient``.  All operations are synchronous (blocking)
and should be called via ``asyncio.to_thread()`` from async code.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from podman.errors import NotFound as _NotFound
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.podman_client import SilvasonicPodmanClient, _container_info

log = structlog.get_logger()


class ContainerManager:
    """Manage Tier 2 container lifecycle via Podman (ADR-0013).

    All methods are synchronous — call via ``asyncio.to_thread()``.
    """

    def __init__(self, podman_client: SilvasonicPodmanClient) -> None:
        """Initialize with a Podman client instance."""
        self._podman = podman_client

    def start(self, spec: Tier2ServiceSpec) -> dict[str, object] | None:
        """Start a Tier 2 container from a spec.

        Returns container info dict on success, None on failure.
        """
        if not self._podman.is_connected:
            log.warning("container_manager.start.not_connected")
            return None

        # Check if container already exists
        existing = self.get(spec.name)
        if existing is not None:
            log.info(
                "container_manager.start.already_exists",
                name=spec.name,
                status=existing.get("status"),
            )
            return existing

        try:
            # Build podman run kwargs from spec
            mounts = [
                {
                    "type": "bind",
                    "source": m.source,
                    "target": m.target,
                    "read_only": m.read_only,
                }
                for m in spec.mounts
            ]

            # Ensure bind-mount source directories exist on the HOST.
            # Use controller_source (controller-local path via bind mount)
            # so mkdir goes through to the host filesystem.
            for mount_spec in spec.mounts:
                mkdir_path = Path(mount_spec.controller_source or mount_spec.source)
                if not mount_spec.read_only and not mkdir_path.exists():
                    mkdir_path.mkdir(parents=True, exist_ok=True)
                    log.info(
                        "container_manager.mkdir",
                        path=str(mkdir_path),
                        name=spec.name,
                    )

            run_kwargs: dict[str, object] = {
                "image": spec.image,
                "name": spec.name,
                "detach": True,
                "network_mode": "bridge",
                "networks": {spec.network: {}},
                "environment": spec.environment,
                "labels": spec.labels,
                "mounts": mounts,
                "privileged": spec.privileged,
                "restart_policy": {
                    "Name": spec.restart_policy.name,
                    "MaximumRetryCount": spec.restart_policy.max_retry_count,
                },
                # Resource Limits (ADR-0020)
                "mem_limit": spec.memory_limit,
                "cpu_quota": int(spec.cpu_limit * 100_000),
                "oom_score_adj": spec.oom_score_adj,
            }

            # Only pass devices/group_add when non-empty; podman-py
            # crashes with TypeError if either is None.
            if spec.devices:
                run_kwargs["devices"] = spec.devices
            if spec.group_add:
                run_kwargs["group_add"] = spec.group_add

            container = self._podman.containers.run(**run_kwargs)

            log.info(
                "container_manager.started",
                name=spec.name,
                image=spec.image,
                memory_limit=spec.memory_limit,
                oom_score_adj=spec.oom_score_adj,
            )

            return _container_info(container)
        except Exception as e:
            log.exception(
                "container_manager.start.failed", name=spec.name, error_type=type(e).__name__
            )
            return None

    def stop(self, name: str, timeout: int = 10) -> bool:
        """Stop a container by name (SIGTERM → wait → force-kill).

        Returns True if stopped, False on error.
        """
        if not self._podman.is_connected:
            return False

        try:
            container = self._podman.containers.get(name)
            container.stop(timeout=timeout)
            log.info("container_manager.stopped", name=name)
            return True
        except _NotFound:
            log.info("container_manager.stop.already_gone", name=name)
            return True
        except Exception as e:
            log.warning("container_manager.stop.failed", name=name, error_type=type(e).__name__)
            return False

    def remove(self, name: str) -> bool:
        """Remove a stopped container.

        Returns True if removed, False on error.
        """
        if not self._podman.is_connected:
            return False

        try:
            container = self._podman.containers.get(name)
            container.remove(force=True)
            log.info("container_manager.removed", name=name)
            return True
        except _NotFound:
            log.info("container_manager.remove.already_gone", name=name)
            return True
        except Exception as e:
            log.warning("container_manager.remove.failed", name=name, error_type=type(e).__name__)
            return False

    def get(self, name: str) -> dict[str, object] | None:
        """Get container info by name, or None if not found."""
        if not self._podman.is_connected:
            return None

        try:
            container = self._podman.containers.get(name)
            return _container_info(container)
        except _NotFound:
            return None
        except Exception as e:
            log.warning("container_manager.get.failed", name=name, error_type=type(e).__name__)
            return None

    def list_managed(self) -> list[dict[str, object]]:
        """List all containers owned by this Controller."""
        return self._podman.list_managed_containers()

    def sync_state(
        self,
        desired: list[Tier2ServiceSpec],
        actual: list[dict[str, object]],
    ) -> None:
        """Synchronize desired vs. actual container state (ADR-0017).

        - Start containers that are desired but not running.
        - Stop containers that are running but not desired.
        - Adopt containers that are already running and desired.

        Args:
            desired: Specs for containers that should be running.
            actual: Info dicts for containers currently running.
        """
        desired_names = {spec.name for spec in desired}
        actual_names = {str(c.get("name", "")) for c in actual}

        # Start missing containers
        for spec in desired:
            if spec.name not in actual_names:
                log.info("reconciler.starting_missing", name=spec.name)
                self.start(spec)
            else:
                log.debug("reconciler.already_running", name=spec.name)

        # Stop and remove orphaned containers (ADR-0017: immutable → recreate)
        for container in actual:
            name = str(container.get("name", ""))
            if name not in desired_names:
                log.info("reconciler.stopping_orphaned", name=name)
                self.stop(name)
                self.remove(name)
