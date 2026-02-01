import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any

import structlog
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import AsyncSessionLocal
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.core.redis.subscriber import RedisSubscriber
from silvasonic.core.schemas.control import ControlMessage
from silvasonic.recorder.manager import ProfileManager
from silvasonic.recorder.stream import FFmpegStreamer
from sqlalchemy import select

logger = structlog.get_logger()

# Configuration
MIC_NAME = os.getenv("MIC_NAME", "default")
MIC_PROFILE_NAME = os.getenv("MIC_PROFILE", "ultramic_384_evo")
ALSA_INDEX_STR = os.getenv("ALSA_DEVICE_INDEX")
ALSA_INDEX = int(ALSA_INDEX_STR) if ALSA_INDEX_STR and ALSA_INDEX_STR.strip() else None

# Paths
# In-container path for recordings
OUTPUT_DIR = Path("/data/recorder") / MIC_NAME / "recordings"


async def fetch_device_config(device_name: str) -> dict[str, Any] | None:
    """Fetch specific device config from DB."""
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(Device).where(Device.name == device_name)
            result = await session.execute(stmt)
            device = result.scalar_one_or_none()
            if device:
                return device.config
            logger.warning("device_not_found_in_db", device=device_name)
            return None
    except Exception as e:
        logger.error("db_fetch_failed", error=str(e))
        # Don't crash on DB failure, fallback to YAML
        return None


async def run_recorder_loop(publisher: RedisPublisher) -> None:
    """Main async loop for the recorder service."""
    # 1. Load Configuration
    profile_manager = ProfileManager()
    db_config = await fetch_device_config(MIC_NAME)

    try:
        profile = profile_manager.load_profile(MIC_PROFILE_NAME, db_config)
        logger.info("profile_loaded", profile=profile.model_dump())
    except Exception as e:
        logger.critical("profile_load_failed", error=str(e))
        await publisher.publish_lifecycle("crashed", reason=f"Profile load failed: {e}")
        sys.exit(1)

    # 2. Init FFmpeg Streamer
    loop = asyncio.get_running_loop()

    def on_segment_complete_sync(filename: str, duration: float) -> None:
        """Callback to handle segment completion from streamer thread."""
        logger.info("recorder_segment_finished", filename=filename, duration=duration)
        asyncio.run_coroutine_threadsafe(
            publisher.publish_audit(
                event="recording.finished",
                payload={
                    "filename": Path(filename).name,
                    "duration": duration,
                },
            ),
            loop,
        )

    streamer = FFmpegStreamer(
        profile=profile,
        output_dir=OUTPUT_DIR,
        alsa_card_index=ALSA_INDEX,
        segment_time_s=60,
        on_segment_complete=on_segment_complete_sync,
    )

    # 3. Signals (Sync boilerplate for generic signal handling)
    def handle_signal(signum: int, frame: object) -> None:
        logger.info("signal_received", signal=signum)
        streamer.stop()
        # We can't await in a sync signal handler easily without a loop ref.
        # But we can rely on finally block below if we raise SystemExit
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # 4. Run Loop
    await publisher.publish_lifecycle("started", reason="Service startup")

    # Subscriber Setup
    subscriber = RedisSubscriber(service_name="recorder", instance_id=MIC_NAME)

    async def handle_reload_config(msg: ControlMessage) -> None:
        logger.info("reloading_configuration", initiator=msg.initiator)
        # TODO: Implement actual reload logic
        # For now, just log it.
        logger.info("configuration_reloaded")

    subscriber.register_handler("reload_config", handle_reload_config)
    await subscriber.start()

    try:
        streamer.start()

        while True:
            # Heartbeat Loop
            await publisher.publish_status(
                status="online",
                activity="recording",
                message=f"Recording {MIC_NAME}",
                meta={
                    "profile": MIC_PROFILE_NAME,
                    "alsa_index": ALSA_INDEX,
                },
            )
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        logger.info("recorder_stopped_by_user")
    except Exception as e:
        logger.critical("recorder_crashed", error=str(e))
        await publisher.publish_lifecycle("crashed", reason=str(e))
        streamer.stop()
        sys.exit(1)
    finally:
        logger.info("recorder_shutdown")
        await subscriber.stop()
        await publisher.publish_lifecycle("stopping", reason="Shutdown signal")
        streamer.stop()


def main() -> None:
    """Execute the main recorder loop."""
    # Basic Logger Setup
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    logger.info("service_startup", service="recorder", mic_name=MIC_NAME)

    publisher = RedisPublisher(service_name="recorder", instance_id=MIC_NAME)

    try:
        asyncio.run(run_recorder_loop(publisher))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
