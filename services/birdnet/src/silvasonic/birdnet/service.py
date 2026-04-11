"""BirdNET inference worker."""

import asyncio
import gc
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf  # type: ignore[import-untyped]
import structlog
from ai_edge_litert.interpreter import Interpreter  # type: ignore[import-untyped]
from silvasonic.birdnet.birdnet_stats import BirdnetStats
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.session import get_session
from silvasonic.core.schemas.detections import BirdnetDetectionDetails
from silvasonic.core.schemas.system_config import BirdnetSettings, SystemSettings
from silvasonic.core.service import SilvaService
from sqlalchemy import func, select

log = structlog.get_logger()

# Constants
MODEL_SR = 48000
WINDOW_SECS = 3.0
WINDOW_SAMPLES = int(WINDOW_SECS * MODEL_SR)

MODEL_DIR = Path(os.environ.get("SILVASONIC_BIRDNET_MODEL_DIR", "/app/models"))
MODEL_PATH = MODEL_DIR / "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite"
META_MODEL_PATH = MODEL_DIR / "BirdNET_GLOBAL_6K_V2.4_MData_Model_V2_FP16.tflite"
LABELS_PATH = MODEL_DIR / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"


def _derive_model_version(filename: str) -> str:
    """Extract model version dynamically from the filename to satisfy data contract."""
    # Example: "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite" -> "v2.4"
    match = re.search(r"V(\d+\.\d+)", filename, re.IGNORECASE)
    if match:
        return f"v{match.group(1)}"
    return "v0.0-unknown"


def _flat_sigmoid(x: np.ndarray, sensitivity: float = 1.0) -> np.ndarray:
    """BirdNET sigmoid calculation (negative sensitivity matches birdnetlib/analyzer)."""
    res = 1.0 / (1.0 + np.exp(sensitivity * np.clip(x, -15, 15)))
    return res  # type: ignore[no-any-return]


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
        self.env_settings = env_settings
        self.birdnet_config: BirdnetSettings | None = None
        self.system_config: SystemSettings | None = None
        self.model_version = _derive_model_version(MODEL_PATH.name)
        self.recordings_dir = Path(env_settings.RECORDINGS_DIR)

        # Initialize Two-Phase Logging stats
        self.stats = BirdnetStats()

        # Snapshot Refresh: monitor birdnet tuning + system location (ADR-0031)
        self._config_keys = ["birdnet", "system"]
        self._backlog_pending: int = 0

    def get_extra_meta(self) -> dict[str, Any]:
        """Inject backlog and operational metrics into the Redis heartbeat (Phase 5)."""
        return {
            "analysis": {
                "backlog_pending": self._backlog_pending,
                "total_analyzed": self.stats.total_analyzed,
                "total_detections": self.stats.total_hits,
                "total_errors": self.stats.total_errors,
                "avg_inference_ms": round(
                    (self.stats.total_duration_s / max(1, self.stats.total_analyzed)) * 1000, 1
                ),
            },
        }

    async def load_config(self) -> None:
        """Load runtime configuration from the database."""
        from silvasonic.core.database.models.system import SystemConfig
        from sqlalchemy import select

        async with get_session() as session:
            stmt = select(SystemConfig).where(SystemConfig.key.in_(["birdnet", "system"]))
            result = await session.execute(stmt)
            configs = {row.key: row.value for row in result.scalars()}

            self.birdnet_config = BirdnetSettings(**configs.get("birdnet", {}))
            self.system_config = SystemSettings(**configs.get("system", {}))

    def _get_allowed_species_mask(self, labels: list[str]) -> tuple[np.ndarray, bool]:
        """Generate static numpy boolean mask for allowed species in current location."""
        assert self.system_config is not None

        loc_filter_active = False
        allowed_mask = np.ones(len(labels), dtype=bool)

        if self.system_config.latitude is not None and self.system_config.longitude is not None:
            # We must run the meta-model to determine allowed species
            loc_filter_active = True
            try:
                from datetime import UTC, datetime

                # Calculate week of year (1-52), mapping to 1-48 for BirdNET
                week_48 = max(1, min(48, int(datetime.now(UTC).isocalendar()[1] * 48 / 52)))

                meta_interp = Interpreter(model_path=str(META_MODEL_PATH), num_threads=1)
                meta_interp.allocate_tensors()
                meta_in = meta_interp.get_input_details()[0]["index"]
                meta_out = meta_interp.get_output_details()[0]["index"]

                meta_input = np.array(
                    [[self.system_config.latitude, self.system_config.longitude, week_48]],
                    dtype=np.float32,
                )
                meta_interp.set_tensor(meta_in, meta_input)
                meta_interp.invoke()

                # Threshold >= 0.03 according to spike finding
                loc_filter = meta_interp.get_tensor(meta_out)[0]
                allowed_mask = loc_filter >= 0.03
                log.info(
                    "birdnet.location_filter_active",
                    species_allowed=int(np.sum(allowed_mask)),
                )
            except Exception as e:
                log.warning("birdnet.location_filter_failed", error=str(e))
                loc_filter_active = False

        return allowed_mask, loc_filter_active

    async def _process_recording(
        self,
        recording: Recording,
        audio_path: Path,
        interpreter: Interpreter,
        labels: list[str],
        allowed_mask: np.ndarray,
        loc_filter_active: bool,
    ) -> list[Detection]:
        """Perform native inference on a single recording."""
        assert self.birdnet_config is not None
        assert self.system_config is not None

        loop = asyncio.get_running_loop()

        # Load audio blocking call bound to executor
        def _load() -> np.ndarray:
            audio, sr = sf.read(str(audio_path), dtype="float32")
            if sr != MODEL_SR:
                log.warning(
                    "birdnet.resampling_skipped",
                    file=str(audio_path),
                    actual_sr=sr,
                    expected_sr=MODEL_SR,
                )
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            return audio  # type: ignore[no-any-return]

        audio = await loop.run_in_executor(None, _load)

        # Slice segments
        overlap = self.birdnet_config.overlap
        step = int((WINDOW_SECS - overlap) * MODEL_SR)
        min_samples = int(1.5 * MODEL_SR)

        detections: list[Detection] = []
        input_idx = interpreter.get_input_details()[0]["index"]
        output_idx = interpreter.get_output_details()[0]["index"]

        # Fast inversion for sigmoid according to spike v3
        adj_sens = max(0.5, min(1.0 - (self.birdnet_config.sensitivity - 1.0), 1.5))

        for start_idx in range(0, len(audio), step):
            if self._shutdown_event.is_set():
                break

            chunk = audio[start_idx : start_idx + WINDOW_SAMPLES]
            if len(chunk) < min_samples:
                break
            if len(chunk) < WINDOW_SAMPLES:
                padded = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
                padded[: len(chunk)] = chunk
                chunk = padded

            # Inference
            def _infer(c: np.ndarray = chunk) -> np.ndarray:
                interpreter.set_tensor(input_idx, c.reshape(1, WINDOW_SAMPLES))
                interpreter.invoke()
                return interpreter.get_tensor(output_idx)[0]  # type: ignore[no-any-return]

            raw = await loop.run_in_executor(None, _infer)
            scores = _flat_sigmoid(raw, sensitivity=-adj_sens)

            # Mask and threshold filter
            mask = (scores >= self.birdnet_config.confidence_threshold) & allowed_mask
            hits = np.where(mask)[0]

            from datetime import timedelta

            w_start_td = timedelta(seconds=start_idx / MODEL_SR)
            w_end_td = w_start_td + timedelta(seconds=WINDOW_SECS)

            for i in hits:
                score = float(scores[i])
                parts = labels[i].split("_")

                details = BirdnetDetectionDetails(
                    model_version=self.model_version,
                    sensitivity=self.birdnet_config.sensitivity,
                    overlap=self.birdnet_config.overlap,
                    confidence_threshold=self.birdnet_config.confidence_threshold,
                    location_filter_active=loc_filter_active,
                    lat=self.system_config.latitude,
                    lon=self.system_config.longitude,
                    week=None,  # Week logic simplified out of payload for brevity
                )

                det = Detection(
                    recording_id=recording.id,
                    worker="birdnet",
                    time=recording.time + w_start_td,
                    end_time=recording.time + w_end_td,
                    label=f"{parts[0]}_{parts[1]}" if len(parts) > 1 else parts[0],
                    common_name=parts[1] if len(parts) > 1 else "",
                    confidence=score,
                    details=details.model_dump(),
                )
                detections.append(det)

        # Explicit memory cleanup
        del audio
        gc.collect()

        return detections

    async def run(self) -> None:
        """Main inference loop."""
        assert self.birdnet_config is not None, "BirdNET DB config not loaded"
        assert self.system_config is not None, "System DB config not loaded"

        self.health.update_status("birdnet", True, "initializing native engine")

        try:
            with open(LABELS_PATH) as f:
                labels = [line.strip() for line in f.readlines()]

            interpreter = Interpreter(
                model_path=str(MODEL_PATH), num_threads=self.birdnet_config.threads
            )
            interpreter.allocate_tensors()

            allowed_mask, loc_filter_active = self._get_allowed_species_mask(labels)

        except Exception as e:
            log.error("birdnet.init_failed", error=str(e))
            self.health.update_status("birdnet", False, str(e))
            await asyncio.sleep(5)
            # Crash fast
            return

        self.health.update_status("birdnet", True, "idle")

        while not self._shutdown_event.is_set():
            self.health.touch()
            self.stats.maybe_emit_summary()

            # --- Snapshot Refresh: reload tuning parameters (ADR-0031) ---
            prev_lat = self.system_config.latitude if self.system_config else None
            prev_lon = self.system_config.longitude if self.system_config else None
            await self._refresh_config()
            # Recompute species mask only if location actually changed
            if self.system_config and (
                self.system_config.latitude != prev_lat or self.system_config.longitude != prev_lon
            ):
                allowed_mask, loc_filter_active = self._get_allowed_species_mask(labels)
                log.info(
                    "birdnet.species_mask_recomputed",
                    lat=self.system_config.latitude,
                    lon=self.system_config.longitude,
                )

            # Backlog update (for heartbeat meta)
            try:
                async with get_session() as session:
                    count_result = await session.execute(
                        select(func.count())
                        .select_from(Recording)
                        .where(Recording.local_deleted.is_(False))
                        .where(~Recording.analysis_state.has_key("birdnet"))
                    )
                    self._backlog_pending = count_result.scalar_one()
            except Exception:
                pass  # Best-effort — keep last known value

            try:
                self.health.update_status("birdnet", True, "polling")

                # Worker Pull ORM
                async with get_session() as session:
                    # Ascending / Descending processing order
                    sort_col = Recording.time.asc()
                    if self.birdnet_config.processing_order == "newest_first":
                        sort_col = Recording.time.desc()

                    # SELECT FOR UPDATE SKIP LOCKED
                    stmt = (
                        select(Recording)
                        .where(Recording.local_deleted.is_(False))
                        .where(~Recording.analysis_state.has_key("birdnet"))
                    )
                    stmt = stmt.order_by(sort_col).limit(1).with_for_update(skip_locked=True)

                    result = await session.execute(stmt)
                    recording = result.scalar_one_or_none()

                    if recording is None:
                        # No work found, sleep
                        await asyncio.sleep(self.env_settings.POLLING_INTERVAL_S)
                        continue

                    # Check file existence — DB stores relative paths, prefix with recordings_dir
                    rel_path = recording.file_processed or recording.file_raw
                    audio_path = self.recordings_dir / rel_path
                    if not audio_path.exists():
                        log.error("birdnet.file_missing", path=str(audio_path))
                        # Mark as failed in DB to prevent infinite loop
                        recording.analysis_state = {"birdnet": "failed_file_missing"}
                        await session.commit()
                        continue

                    # Process
                    self.health.update_status("birdnet", True, f"analyzing {recording.id}")
                    start_time = time.perf_counter()

                    try:
                        detections = await self._process_recording(
                            recording,
                            audio_path,
                            interpreter,
                            labels,
                            allowed_mask,
                            loc_filter_active,
                        )

                        if detections:
                            session.add_all(detections)

                        # Update analysis state using direct mutation / JSON merging
                        # Copy the dict and update to ensure SQLAlchemy notices the mutation
                        new_state = dict(recording.analysis_state)
                        new_state["birdnet"] = "done"
                        recording.analysis_state = new_state

                        await session.commit()
                        elapsed = time.perf_counter() - start_time
                        self.stats.record_analyzed(recording.id, elapsed, len(detections))

                    except Exception as e:
                        self.stats.record_error(recording.id, e)
                        await session.rollback()

                        # Store crash log in state
                        new_state = dict(recording.analysis_state)
                        new_state["birdnet"] = f"crashed: {str(e)[:50]}"
                        recording.analysis_state = new_state
                        await session.commit()

            except Exception as exc:
                # Soft-fail transient DB errors or post-rollback persistence failures (ADR-0030)
                log.warning("birdnet.db_cycle_failed", error=str(exc))
                self.health.update_status("birdnet", False, "database_unavailable")
                await asyncio.sleep(self.env_settings.DB_RETRY_INTERVAL_S)
                continue

        # Emit final summary on shutdown
        self.stats.emit_final_summary()
