from typing import Any

import podman
import structlog
from podman.errors import APIError
from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.settings import ControllerSettings

logger = structlog.get_logger()
settings = ControllerSettings()


class PodmanManager:
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

    def list_active_recorders(self) -> list[dict[str, Any]]:
        """List all active containers managed by Silvasonic Controller."""
        try:
            # We filter by label to only find containers we manage
            containers = self.client.containers.list(
                filters={"label": ["managed_by=silvasonic-controller", "service=recorder"]}
            )

            results = []
            for c in containers:
                results.append(
                    {
                        "id": c.id,
                        "name": c.name,
                        "status": c.status,
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

        # Profile specific logic: we mount specific subfolders
        # /etc/silvasonic/profiles is the target inside recorder
        # Host source: ./services/recorder/config/profiles -> need absolute path or relative to context
        # In this architecture, we might need a simpler approach:
        # The controller doesn't easily know the absolute source path of the code on the host unless mapped.
        # For now, let's assume the standard layout.

        # ACTUALLY: The "Template" pattern suggests we might reuse the image definition?
        # But we are using `podman run`. We need to define volumes explicitly.
        # Let's use the layout defined in FS Governance.

        volumes = [
            f"{host_root}/recordings:/data/recordings:z",
            # We assume the profiles are also available on the host at a known location
            # OR we rely on them being baked into the image?
            # Looking at recorder Dockerfile: it COPIES nothing about profiles?
            # Wait, verify_dodotronic mounts `./services/recorder/config/profiles`.
            # We need to access that.
            # Ideally, the controller should mount the profiles dir from the host.
            # Let's assume it's at {host_root}/config/profiles for now or pass via Env?
            # Creating a 'config' volume is safer.
        ]

        # For now, let's follow the `verify_dodotronic` pattern but adapting to absolute paths
        # if possible. If not, we might need to rely on the user to have mounted profiles to a known spot
        # or bake them into the image (which is cleaner for an appliance).
        # Let's assume for this MVP that profiles are mounted at /etc/silvasonic/profiles on the HOST?
        # No, that's host OS pollution.

        # WORKAROUND: We will assume the repository is checked out at /app/repo (mounted) or similar?
        # No.

        # Let's look at `podman-compose.yml` for the standard recorder service:
        # volumes: ./services/recorder/config/profiles:/etc/silvasonic/profiles:ro,z

        # So we need to replicate that.
        # We will assume that `HOST_DATA_DIR/../services/recorder/config/profiles` exists?
        # No, `HOST_DATA_DIR` is usually `/mnt/data/dev/apps/silvasonic` (The Repo Root in this context?)
        # docs say: HOST_DATA_DIR default: /mnt/data/dev/apps/silvasonic

        # So:
        # For now, we use the Source Dir for profiles (Code) and Data Dir for recordings (Data)
        profiles_host_path = f"{source_root}/services/recorder/config/profiles"
        volumes.append(f"{profiles_host_path}:/etc/silvasonic/profiles:ro,z")

        try:
            # Check if exists and remove if stopped
            try:
                old_c = self.client.containers.get(container_name)
                if old_c.status != "running":
                    logger.info("removing_stale_container", container=container_name)
                    old_c.remove()
                else:
                    logger.warning("container_already_running", container=container_name)
                    return True
            except podman.errors.NotFound:
                pass

            self.client.containers.run(
                image="silvasonic-recorder",
                name=container_name,
                detach=True,
                remove=False,  # We want to debug it if it fails
                environment=env_vars,
                devices=[
                    "/dev/snd:/dev/snd"
                ],  # Pass through all sound for now, or specific? specific is better but harder with /dev/snd/controlC* etc.
                group_add=["keep-groups"],  # Important for audio permissions
                volumes=volumes,
                network="silvasonic-net",  # Must be on same net
                labels={
                    "managed_by": "silvasonic-controller",
                    "service": "recorder",
                    "mic_name": mic_name,
                    "device_serial": serial_number,
                },
            )
            logger.info("recorder_started", container=container_name)
            return True

        except Exception as e:
            logger.error("spawn_failed", error=str(e))
            return False

    def stop_recorder(self, container_id: str) -> bool:
        """Stop a managed recorder."""
        try:
            c = self.client.containers.get(container_id)
            c.stop()
            c.remove()
            logger.info("recorder_stopped", id=container_id)
            return True
        except Exception as e:
            logger.error("stop_failed", error=str(e))
            return False
