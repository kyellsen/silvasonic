from typing import Any

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

    def list_active_services(self) -> list[dict[str, Any]]:
        """List all active containers managed by Silvasonic Controller."""
        try:
            # We filter by label to only find containers we manage
            containers = self.client.containers.list(
                filters={"label": ["managed_by=silvasonic-controller"]}
            )

            results = []
            for c in containers:
                results.append(
                    {
                        "id": c.id,
                        "name": c.name,
                        "status": c.status,
                        "service": c.labels.get("service"),
                        "device_serial": c.labels.get("device_serial"),
                        "mic_name": c.labels.get("mic_name"),
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
        container_name = f"silvasonic-recorder-{mic_name}"
        logger.info("spawning_recorder", container=container_name, device=device.display_name)

        # Environment Variables
        env_vars = {
            "MIC_NAME": mic_name,
            "MIC_PROFILE": mic_profile,
            "ALSA_DEVICE_INDEX": str(device.card_index),
            "PYTHONUNBUFFERED": "1",
        }

        # Volumes
        # We must inject the bindings relative to the host view.
        # The HOST_DATA_DIR setting comes from env var injected into Controller.
        host_root = settings.HOST_DATA_DIR
        source_root = settings.HOST_SOURCE_DIR

        volumes = [
            f"{host_root}/recorder:/data/recorder:z",
            # We assume the profiles are also available on the host at a known location
            f"{source_root}/services/recorder/config/profiles:/etc/silvasonic/profiles:ro,z",
        ]

        return self._spawn_container(
            name=container_name,
            image="silvasonic-recorder",
            env=env_vars,
            volumes=volumes,
            devices=["/dev/snd:/dev/snd"],
            labels={
                "managed_by": "silvasonic-controller",
                "service": "recorder",
                "mic_name": mic_name,
                "device_serial": serial_number,
            },
            group_add=["keep-groups"],
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

    def _spawn_container(
        self,
        name: str,
        image: str,
        env: dict[str, str],
        volumes: list[str],
        labels: dict[str, str],
        devices: list[str] | None = None,
        group_add: list[str] | None = None,
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

            self.client.containers.run(
                image=image,
                name=name,
                detach=True,
                remove=False,
                environment=env,
                devices=devices or [],
                group_add=group_add or [],
                volumes=volumes,
                network="silvasonic-net",
                labels=labels,
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
