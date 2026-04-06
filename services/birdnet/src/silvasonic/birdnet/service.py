"""BirdNET inference worker."""

import asyncio

from silvasonic.core.config_schemas import BirdnetSettings, SystemSettings
from silvasonic.core.service import SilvaService


class BirdNETService(SilvaService):
    """BirdNET singleton background worker.

    Pulls unanalyzed audio segments from the database, runs the native
    ai-edge-litert model, and stores detections.
    """

    service_name = "birdnet"
    service_port = 9500

    def __init__(self) -> None:
        """Initialize the BirdNET service."""
        from silvasonic.birdnet.settings import BirdnetEnvSettings

        env_settings = BirdnetEnvSettings()

        super().__init__(
            instance_id=env_settings.INSTANCE_ID,
            redis_url=env_settings.REDIS_URL,
            heartbeat_interval=env_settings.HEARTBEAT_INTERVAL_S,
        )
        self.birdnet_config: BirdnetSettings | None = None
        self.system_config: SystemSettings | None = None

    async def load_config(self) -> None:
        """Load runtime configuration from the database."""
        from silvasonic.core.database.models.system import SystemConfig
        from silvasonic.core.database.session import get_session
        from sqlalchemy import select

        async with get_session() as session:
            stmt = select(SystemConfig).where(SystemConfig.key.in_(["birdnet", "system"]))
            result = await session.execute(stmt)
            configs = {row.key: row.value for row in result.scalars()}

            self.birdnet_config = BirdnetSettings(**configs.get("birdnet", {}))
            self.system_config = SystemSettings(**configs.get("system", {}))

    async def run(self) -> None:
        """Main inference loop."""
        assert self.birdnet_config is not None, "BirdNET DB config not loaded"
        assert self.system_config is not None, "System DB config not loaded"

        self.health.update_status("birdnet", True, "idle")

        while not self._shutdown_event.is_set():
            self.health.touch()
            # Phase 3 will implement Worker Pull via FOR UPDATE SKIP LOCKED
            await asyncio.sleep(1.0)
