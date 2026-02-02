import os
from typing import Any, cast

import podman
import structlog
from podman.errors import APIError
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.settings import ControllerSettings

logger = structlog.get_logger()
settings = ControllerSettings()


class PodmanOrchestrator:
    """Manages Podman containers via the Unix Socket."""

    def __init__(self) -> None:
        """Initialize the Podman client."""
        self.client = podman.PodmanClient(base_url=settings.PODMAN_SOCKET_URL)

    def is_connected(self) -> bool:
        """Check if connection to Podman socket is alive."""
        try:
            return bool(self.client.ping())
        except Exception as e:
            logger.error("podman_connection_failed", error=str(e))
            return False

    def _get_safe_status(self, container: Any) -> str:
        """Safely get container status, handling different API return shapes."""
        try:
            return cast(str, container.status)
        except TypeError:
            # Fallback: State might be a direct string (e.g. 'running') in list() summary
            state = container.attrs.get("State")
            if isinstance(state, str):
                return state.lower()
            # If we really can't determine, assume unknown
            return "unknown"

    def list_active_services(self) -> list[dict[str, Any]]:
        """List all active containers managed by Silvasonic Controller."""
        try:
            # We list ALL containers and filter in Python to be robust
            # API filtering can sometimes be finicky with multiple labels or specific podman versions
            containers = self.client.containers.list(all=True)

            results = []
            for c in containers:
                # Manual Filter
                labels = c.labels or {}
                if labels.get("managed_by") != "silvasonic-controller":
                    continue

                # Only running containers are "active" for our purposes of reconciliation
                # (We want to restart stopped ones)
                status = self._get_safe_status(c)
                if status != "running":
                    continue

                results.append(
                    {
                        "id": c.id,
                        "name": c.name,
                        "status": status,
                        "service": labels.get("service"),
                        "device_serial": labels.get("device_serial"),
                        "mic_name": labels.get("mic_name"),
                        "created": c.attrs.get("Created")
                        if hasattr(c, "attrs")
                        else None,  # Timestamp
                    }
                )
            return results
        except APIError as e:
            logger.error("podman_list_failed", error=str(e))
            return []

    def spawn_recorder(
        self, device: AudioDevice, mic_profile: str, mic_name: str, serial_number: str
    ) -> bool:
        """Spawn a new recorder container for a specific device."""
        short_serial = serial_number[-4:].lower() if serial_number else "xxxx"

        # Friendly Name: used for Container Name AND Directory Paths
        friendly_name = f"{mic_profile}-{short_serial}"
        container_name = f"silvasonic-recorder-{friendly_name}"

        logger.info("spawning_recorder", container=container_name, device=device.display_name)

        # Pre-Spawn: Ensure Log Directory exists on Host (via /host_data mount)
        try:
            # /host_data maps to settings.HOST_DATA_DIR
            # WE NOW USE friendly_name HERE INSTEAD OF mic_name
            internal_log_path = f"/host_data/recorder/{friendly_name}/logs"
            os.makedirs(internal_log_path, exist_ok=True)
            # Ensure permissions? Rootless inside container might own it as root (mapped to user outside)
            # which is fine.
        except Exception as e:
            logger.error("failed_to_create_log_dir", path=internal_log_path, error=str(e))

        # Environment Variables
        env_vars = {
            "MIC_NAME": friendly_name,  # Updated to match directory
            "MIC_PROFILE": mic_profile,
            "ALSA_DEVICE_INDEX": str(device.card_index),
            "PYTHONUNBUFFERED": "1",
            "LOG_DIR": "/var/log/silvasonic",
            "SILVASONIC_REDIS_HOST": settings.REDIS_HOST,  # Required by silvasonic.core
            "ICECAST_HOST": settings.ICECAST_HOST,
        }

        # Volumes
        # We must inject the bindings relative to the host view.
        # The HOST_DATA_DIR setting comes from env var injected into Controller.
        host_root = settings.HOST_DATA_DIR
        source_root = settings.HOST_SOURCE_DIR

        volumes = [
            # USE friendly_name for both host and container paths
            f"{host_root}/recorder/{friendly_name}:/data/recorder/{friendly_name}:z",
            # We assume the profiles are also available on the host at a known location
            f"{source_root}/services/recorder/config/profiles:/etc/silvasonic/profiles:ro,z",
            # Inject Host Logs
            f"{host_root}/recorder/{friendly_name}/logs:/var/log/silvasonic:z",
        ]

        return self._spawn_container(
            name=container_name,
            image="localhost/silvasonic-recorder",
            env=env_vars,
            volumes=volumes,
            devices=["/dev/snd:/dev/snd"],
            labels={
                "managed_by": "silvasonic-controller",
                "service": "recorder",
                "mic_name": mic_name,  # Keep original Logical Name in labels for DB reconciliation
                "device_serial": serial_number,
            },
            security_opt=[],
            privileged=True,
            network="silvasonic_silvasonic-net",
        )

    def spawn_service(
        self, service_name: str, image: str, env: dict[str, str], volumes: list[str]
    ) -> bool:
        """Spawn a generic Tier 2 service."""
        container_name = f"silvasonic-{service_name}"
        logger.info("spawning_service", service=service_name)

        # Standard Labels
        labels = {
            "managed_by": "silvasonic-controller",
            "service": service_name,
            "silvasonic.service": service_name,
        }

        return self._spawn_container(
            name=container_name,
            image=image,
            env=env,
            volumes=volumes,
            labels=labels,
        )

    def _convert_volumes_to_mounts(self, volumes: list[str]) -> list[dict[str, Any]]:
        """Convert list of volume strings to Mount dictionaries."""
        mounts = []
        for vol in volumes:
            parts = vol.split(":")
            if len(parts) < 2:
                continue

            source = parts[0]
            target = parts[1]
            options = parts[2] if len(parts) > 2 else ""

            # Basic Mount structure
            mount: dict[str, Any] = {
                "Source": source,
                "Target": target,
                "Type": "bind",
            }

            # Handle Read-Only
            if "ro" in options:
                mount["ReadOnly"] = True

            mounts.append(mount)
        return mounts

    def _spawn_container(
        self,
        name: str,
        image: str,
        env: dict[str, str],
        volumes: list[str],
        labels: dict[str, str],
        devices: list[str] | None = None,
        group_add: list[str] | None = None,
        security_opt: list[str] | None = None,
        privileged: bool = False,
        network: str = "silvasonic_silvasonic-net",
    ) -> bool:
        """Internal helper to spawn containers safely."""
        try:
            # Check if exists and remove if stopped
            try:
                old_c = self.client.containers.get(name)
                if old_c.status != "running":
                    logger.info("removing_stale_container", container=name)
                    old_c.remove()
                else:
                    logger.warning("container_already_running", container=name)
                    return True
            except podman.errors.NotFound:
                pass

            # Convert volumes to mounts
            mounts = self._convert_volumes_to_mounts(volumes)

            self.client.containers.run(
                image=image,
                name=name,
                detach=True,
                remove=False,
                environment=env,
                devices=devices or [],
                group_add=group_add or [],
                mounts=mounts,
                # Use correct network name created by podman-compose
                network=network,
                labels=labels,
                security_opt=security_opt or [],
                privileged=privileged,
            )
            logger.info("container_started", container=name)
            return True

        except Exception as e:
            logger.error("spawn_failed", error=str(e), container=name)
            return False

    def stop_service(self, container_id: str) -> bool:
        """Stop a managed container."""
        try:
            c = self.client.containers.get(container_id)
            c.stop()
            c.remove()
            logger.info("service_stopped", id=container_id)
            return True
        except Exception as e:
            logger.error("stop_failed", error=str(e), id=container_id)
            return False


# Alias for backward compatibility if needed, but we will refactor usage.
PodmanManager = PodmanOrchestrator
