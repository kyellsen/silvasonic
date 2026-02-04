import asyncio
import os
import signal
import sys
from pathlib import Path

import structlog
from silvasonic.core.logging import configure_logging
from silvasonic.core.monitoring import ResourceMonitor
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.core.redis.subscriber import RedisSubscriber
from silvasonic.core.schemas.control import ControlMessage
from silvasonic.recorder.manager import ProfileManager
from silvasonic.recorder.settings import settings
from silvasonic.recorder.stream import FFmpegStreamer

logger = structlog.get_logger()

# Paths
# In-container path for recordings
OUTPUT_DIR = Path("/data/recorder") / settings.MIC_NAME / "recordings"

# Resource Monitor (watches storage at output path)
monitor = ResourceMonitor(storage_path=OUTPUT_DIR)


async def run_recorder_loop(publisher: RedisPublisher | None = None) -> None:
    """Main async loop for the recorder service."""
    # 1. Load Configuration
    profile_manager = ProfileManager()

    # Configuration is now purely Environment-driven (Orchestrator responsibility)

    try:
        # Pass empty config dict as overrides, or rely purely on profile + env vars
        profile = profile_manager.load_profile(settings.MIC_PROFILE, {})
        logger.info("profile_loaded", profile=profile.model_dump())
    except Exception as e:
        logger.critical("profile_load_failed", error=str(e))
        try:
            if publisher:
                await publisher.publish_lifecycle("crashed", reason=f"Profile load failed: {e}")
        except Exception:
            pass  # Fail safe if redis is down, we are crashing anyway
        sys.exit(1)

    # 2. Init FFmpeg Streamer
    loop = asyncio.get_running_loop()

    def on_segment_complete_sync(filename: str, duration: float) -> None:
        """Callback to handle segment completion from streamer thread."""
        logger.info("recorder_segment_finished", filename=filename, duration=duration)
        try:
            if publisher:
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
        except Exception as e:
            logger.warning("audit_publish_failed", error=str(e))

    streamer = FFmpegStreamer(
        profile=profile,
        output_dir=OUTPUT_DIR,
        alsa_card_index=settings.ALSA_DEVICE_INDEX,
        on_segment_complete=on_segment_complete_sync,
        live_stream_url=settings.live_stream_url,
        input_format=settings.INPUT_FORMAT,
        input_device=settings.INPUT_DEVICE_OVERRIDE,
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
    try:
        if publisher:
            await publisher.publish_lifecycle("started", reason="Service startup", pid=os.getpid())
    except Exception as e:
        logger.warning("lifecycle_startup_failed", error=str(e))

    # Subscriber Setup
    subscriber = RedisSubscriber(service_name="recorder", instance_id=settings.MIC_NAME)

    async def handle_reload_config(msg: ControlMessage) -> None:
        logger.info("reloading_configuration", initiator=msg.initiator)
        # TODO: Implement actual reload logic
        # For now, just log it.
        logger.info("configuration_reloaded")

    try:
        subscriber.register_handler("reload_config", handle_reload_config)
        await subscriber.start()
    except Exception as e:
        logger.warning("subscriber_start_failed", error=str(e))

    try:
        streamer.start()

        while True:
            # Heartbeat Loop
            if publisher:
                await publisher.publish_status(
                    status="online",
                    activity="recording",
                    message=f"Recording {settings.MIC_NAME}",
                    meta={
                        "profile": settings.MIC_PROFILE,
                        "alsa_index": settings.ALSA_DEVICE_INDEX,
                        "resources": monitor.get_usage(),
                        "stream_url": settings.live_stream_url,
                    },
                )
            await asyncio.sleep(5)

    except KeyboardInterrupt:
        logger.info("recorder_stopped_by_user")
    except Exception as e:
        logger.critical("recorder_crashed", error=str(e))
        try:
            if publisher:
                await publisher.publish_lifecycle("crashed", reason=str(e), pid=os.getpid())
        except Exception:
            pass
        streamer.stop()
        sys.exit(1)
    finally:
        logger.info("recorder_shutdown")
        if publisher:
            try:
                await publisher.publish_lifecycle(
                    "stopping", reason="Shutdown signal", pid=os.getpid()
                )
            except Exception as e:
                logger.warning("lifecycle_stopping_failed", error=str(e))

            try:
                # subscriber is defined in scope above
                if "subscriber" in locals():
                    await subscriber.stop()
            except Exception as e:
                logger.warning("subscriber_stop_failed", error=str(e))
        streamer.stop()


def main() -> None:
    """Execute the main recorder loop."""
    # Configure logging (Dual Config: Stdout + File)
    log_dir = str(settings.LOG_DIR) if settings.LOG_DIR else None
    configure_logging(service_name="recorder", log_dir=log_dir)

    logger.info("service_startup", service="recorder", mic_name=settings.MIC_NAME)

    publisher = RedisPublisher(service_name="recorder", instance_id=settings.MIC_NAME)
    # publisher = None

    try:
        asyncio.run(run_recorder_loop(publisher))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
