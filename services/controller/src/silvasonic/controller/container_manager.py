"""Container lifecycle manager for Tier 2 services (ADR-0013).

Provides a high-level API for managing Tier 2 containers via the
``SilvasonicPodmanClient``.  All operations are synchronous (blocking)
and should be called via ``asyncio.to_thread()`` from async code.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog
from podman.errors import APIError as _APIError
from podman.errors import NotFound as _NotFound
from silvasonic.controller.container_spec import Tier2ServiceSpec
from silvasonic.controller.podman_client import SilvasonicPodmanClient, container_info

log = structlog.get_logger()


class ContainerManager:
    """Manage Tier 2 container lifecycle via Podman (ADR-0013).

    All methods are synchronous — call via ``asyncio.to_thread()``.
    """

    def __init__(
        self,
        podman_client: SilvasonicPodmanClient,
        owner_profile: str = "controller",
    ) -> None:
        """Initialize with a Podman client instance.

        Args:
            podman_client: Connected Podman client.
            owner_profile: Label value for ``io.silvasonic.owner``.
                Defaults to ``"controller"`` (production).  Tests pass
                a unique value to isolate test containers.
        """
        self._podman = podman_client
        self._owner_profile = owner_profile

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
            status = existing.get("status", "")
            if status == "running":
                log.info(
                    "container_manager.start.already_running",
                    name=spec.name,
                )
                return existing

            # Container exists but is not running (exited/dead) — remove
            # and fall through to recreate.  This prevents restart loops
            # when a Recorder crashes.
            log.info(
                "container_manager.start.replacing_exited",
                name=spec.name,
                status=status,
            )
            self.stop_and_remove(spec.name)

        try:
            self._ensure_mount_dirs(spec)
            run_kwargs = self._build_run_kwargs(spec)
            container = self._podman.containers.run(**run_kwargs)

            log.info(
                "container_manager.started",
                name=spec.name,
                image=spec.image,
                memory_limit=spec.memory_limit,
                oom_score_adj=spec.oom_score_adj,
            )

            return container_info(container)
        except Exception as e:
            log.exception(
                "container_manager.start.failed", name=spec.name, error_type=type(e).__name__
            )
            return None

    @staticmethod
    def _ensure_mount_dirs(spec: Tier2ServiceSpec) -> None:
        """Create bind-mount source directories on the host if needed."""
        for mount_spec in spec.mounts:
            mkdir_path = Path(mount_spec.controller_source or mount_spec.source)
            if not mount_spec.read_only and not mkdir_path.exists():
                mkdir_path.mkdir(parents=True, exist_ok=True)
                log.info(
                    "container_manager.mkdir",
                    path=str(mkdir_path),
                    name=spec.name,
                )

    @staticmethod
    def _build_run_kwargs(spec: Tier2ServiceSpec) -> dict[str, object]:
        """Build ``podman.containers.run()`` kwargs from a Tier2ServiceSpec."""
        # Use 'volumes' instead of 'mounts' to pass SELinux/rootless ownership relabeling ('z')
        # podman-py API translates 'ro,z' strictly as a single invalid option to the backend.
        # For read_only mounts, the host directory should already be labeled appropriately
        # by the producer container ('z'), so 'ro' alone is sufficient and avoids the 500 error.
        volumes = {}
        for m in spec.mounts:
            mode = "ro" if m.read_only else "z"
            volumes[m.source] = {"bind": m.target, "mode": mode}

        kwargs: dict[str, object] = {
            "image": spec.image,
            "name": spec.name,
            "detach": True,
            "network_mode": "bridge",
            "networks": {spec.network: {}},
            "environment": spec.environment,
            "labels": spec.labels,
            "volumes": volumes,
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
            kwargs["devices"] = spec.devices
        if spec.group_add:
            kwargs["group_add"] = spec.group_add

        return kwargs

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
        except (json.JSONDecodeError, _APIError):
            # podman-py raises JSONDecodeError when the container exits
            # before the stop response arrives (304 with empty body).
            # APIError may also occur in similar race conditions.
            # In both cases the container is effectively stopped.
            log.info("container_manager.stop.race_ok", name=name)
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
        except _APIError:
            # Container may still be transitioning from 'stopping' → retry once
            time.sleep(2)
            try:
                container = self._podman.containers.get(name)
                container.remove(force=True)
                log.info("container_manager.removed", name=name)
                return True
            except _NotFound:
                log.info("container_manager.remove.already_gone", name=name)
                return True
            except Exception as retry_err:
                log.warning(
                    "container_manager.remove.failed",
                    name=name,
                    error_type=type(retry_err).__name__,
                )
                return False
        except Exception as e:
            log.warning("container_manager.remove.failed", name=name, error_type=type(e).__name__)
            return False

    def stop_and_remove(self, name: str, timeout: int = 10) -> bool:
        """Stop and remove a container (teardown lifecycle).

        Combines ``stop()`` and ``remove()`` into a single idempotent
        operation.  Returns True if the container is gone afterwards.
        """
        self.stop(name, timeout=timeout)
        return self.remove(name)

    def get(self, name: str) -> dict[str, object] | None:
        """Get container info by name, or None if not found."""
        if not self._podman.is_connected:
            return None

        try:
            container = self._podman.containers.get(name)
            return container_info(container)
        except _NotFound:
            return None
        except Exception as e:
            log.warning("container_manager.get.failed", name=name, error_type=type(e).__name__)
            return None

    def list_managed(self) -> list[dict[str, object]]:
        """List all containers owned by this Controller."""
        return self._podman.list_managed_containers(
            owner_profile=self._owner_profile,
        )

    def sync_state(
        self,
        desired: list[Tier2ServiceSpec],
        actual: list[dict[str, object]],
    ) -> None:
        """Synchronize desired vs. actual container state (ADR-0017).

        - Start containers that are desired but not running.
        - Stop containers that are running but not desired.
        - Restart containers whose config_hash has drifted.
        - Adopt containers that are already running and desired.

        Args:
            desired: Specs for containers that should be running.
            actual: Info dicts for containers currently running.
        """
        desired_specs_by_name = {spec.name: spec for spec in desired}
        actual_containers_by_name = {str(c.get("name", "")): c for c in actual}

        # Start missing or drifted containers
        for name, spec in desired_specs_by_name.items():
            actual_container = actual_containers_by_name.get(name)

            if not actual_container:
                log.info("container_manager.starting_missing", name=spec.name)
                self.start(spec)
            else:
                # Type guard for labels dictionary
                labels = actual_container.get("labels", {})
                if not isinstance(labels, dict):
                    labels = {}

                actual_hash = labels.get("io.silvasonic.config_hash", "")

                if actual_hash != spec.config_hash:
                    log.info(
                        "container_manager.restarting_config_drift",
                        name=spec.name,
                        old_hash=actual_hash,
                        new_hash=spec.config_hash,
                    )
                    self.stop_and_remove(name)
                    self.start(spec)
                else:
                    log.debug("container_manager.already_running", name=spec.name)

        # Stop and remove orphaned containers (ADR-0017: immutable → recreate)
        for name in actual_containers_by_name:
            if name not in desired_specs_by_name:
                log.info("container_manager.stopping_orphaned", name=name)
                self.stop_and_remove(name)
