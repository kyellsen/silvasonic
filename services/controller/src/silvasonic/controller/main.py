import asyncio

import structlog
from silvasonic.controller.hardware import AudioDevice, DeviceScanner
from silvasonic.controller.messaging import MessageBroker
from silvasonic.controller.orchestrator import PodmanManager
from silvasonic.controller.settings import ControllerSettings
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import AsyncSessionLocal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()
settings = ControllerSettings()


class ControllerService:
    """Main Service Class for the Controller."""

    def __init__(self) -> None:
        """Initialize dependencies (Scanner, Podman, Metadata broker)."""
        self.scanner = DeviceScanner()
        self.podman = PodmanManager()
        self.broker = MessageBroker()
        self.settings = settings

    async def _get_or_create_device(
        self, session: AsyncSession, audio_device: AudioDevice
    ) -> Device:
        """Find device by Serial Number or create if new."""
        # Try finding by Serial Number
        stmt = select(Device).where(Device.serial_number == audio_device.serial_number)
        result = await session.execute(stmt)
        device = result.scalar_one_or_none()

        if not device:
            # Auto-Enroll
            logical_name = f"mic_{audio_device.serial_number}"

            logger.info(
                "auto_enrolling_device", serial=audio_device.serial_number, name=logical_name
            )

            device = Device(
                name=logical_name,
                serial_number=audio_device.serial_number,
                model=audio_device.description,
                status="online",
                enabled=True,
                config={},
            )
            session.add(device)
            # Flush to get it ready, but commit happens later
            await session.flush()

        return device

    async def reconcile(self) -> None:
        """Main logic loop: Sync Hardware -> DB -> Containers."""
        logger.info("reconciliation_start")

        try:
            if not self.podman.is_connected():
                logger.error("podman_unavailable_skipping_reconcile")
                return

            detected_devices = []
            try:
                # 1. Detect Hardware (Blocking call, fast enough usually)
                loop = asyncio.get_running_loop()
                detected_devices = await loop.run_in_executor(
                    None, self.scanner.find_dodotronic_devices
                )
            except Exception as e:
                logger.error("hardware_scan_failed", error=str(e))
                # We continue with empty list? Or return?
                # If scan fails, we shouldn't assume devices are gone.
                return

            detected_map = {d.serial_number: d for d in detected_devices}

            async with AsyncSessionLocal() as session:
                try:
                    # 2. Update DB State (Online/Offline)
                    result = await session.execute(select(Device))
                    db_devices = result.scalars().all()

                    for db_dev in db_devices:
                        if db_dev.serial_number not in detected_map:
                            if db_dev.status != "offline":
                                logger.info("device_offline", name=db_dev.name)
                                db_dev.status = "offline"

                    active_db_devices = []
                    for _serial, hw_dev in detected_map.items():
                        device = await self._get_or_create_device(session, hw_dev)
                        if device.status != "online":
                            device.status = "online"

                        from datetime import datetime

                        device.last_seen = datetime.utcnow()
                        active_db_devices.append((device, hw_dev))

                    await session.commit()

                    # 3. Orchestrate Containers
                    active_containers = self.podman.list_active_recorders()
                    running_map = {}
                    for c in active_containers:
                        s = c.get("device_serial")
                        if s:
                            running_map[s] = c

                    # A. Start missing
                    for device, hw_dev in active_db_devices:
                        if device.enabled and device.status == "online":
                            if device.serial_number not in running_map:
                                logger.info("starting_service", device=device.name)
                                profile = device.config.get("profile", "ultramic_384_evo")

                                success = self.podman.spawn_recorder(
                                    device=hw_dev,
                                    mic_profile=profile,
                                    mic_name=device.name,
                                    serial_number=device.serial_number,
                                )
                                if not success:
                                    logger.error("failed_to_start_recorder", device=device.name)

                    # B. Stop valid but disabled/offline
                    for serial, container in running_map.items():
                        is_present = serial in detected_map
                        target_device = next(
                            (d for d in db_devices if d.serial_number == serial), None
                        )
                        if not target_device:
                            for d, _ in active_db_devices:
                                if d.serial_number == serial:
                                    target_device = d
                                    break

                        should_run = is_present and target_device and target_device.enabled

                        if not should_run:
                            container_name = container.get("name", "unknown")
                            logger.info(
                                "stopping_service",
                                container=container_name,
                                reason="device_lost_or_disabled",
                            )
                            self.podman.stop_recorder(container["id"])

                except Exception as e:
                    logger.error("reconcile_error", error=str(e))
                    await session.rollback()

            # Publish Heartbeat
            await self.broker.publish_status(
                status="online",
                activity="monitoring",
                message="Controller active",
                meta={"detected_devices": len(detected_devices)},
            )

        except Exception as e:
            logger.error("reconcile_critical_error", error=str(e))
            # Do not re-raise to keep loop alive

    async def run(self) -> None:
        """Start the async scheduler loop."""
        logger.info("controller_service_started")
        while True:
            await self.reconcile()
            await asyncio.sleep(self.settings.SYNC_INTERVAL_SECONDS)


def main() -> None:
    """Entry point for the Controller service."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )

    service = ControllerService()
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("controller_service_stopping")


if __name__ == "__main__":  # pragma: no cover
    main()
