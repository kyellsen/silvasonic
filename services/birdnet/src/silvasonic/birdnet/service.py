"""BirdNET inference worker."""

import asyncio
import gc
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import structlog
from ai_edge_litert.interpreter import Interpreter
from silvasonic.birdnet.birdnet_stats import BirdnetStats
from silvasonic.birdnet.species import label_species_id, register_species
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.recordings import Recording
from silvasonic.core.database.session import get_session
from silvasonic.core.schemas.analysis import (
    CLAIM_LEASE,
    REASON_FILE_MISSING,
    REASON_SAMPLE_RATE_UNSUPPORTED,
    AnalysisClaim,
    AnalysisState,
)
from silvasonic.core.schemas.detections import BirdnetDetectionDetails
from silvasonic.core.schemas.settings import BirdnetSettings, StationSettings
from silvasonic.core.service import SilvaService
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Constants
MODEL_SR = 48000
WINDOW_SECS = 3.0
WINDOW_SAMPLES = int(WINDOW_SECS * MODEL_SR)
# A recording shorter than this is not worth one zero-padded window.
MIN_CHUNK_SAMPLES = int(1.5 * MODEL_SR)
# The seam window spans a segment boundary: this much audio on either side.
SEAM_SAMPLES = WINDOW_SAMPLES // 2
# Segment names are rounded to the second, so consecutive segments of one
# run may appear up to this far apart.
CONTIGUITY_TOLERANCE_S = 1.0

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


class UnsupportedSampleRateError(ValueError):
    """The audio file is not at the model's 48 kHz.

    BirdNET does not resample (ADR-0011): the Recorder's processed stream is
    48 kHz, and a raw-only profile is valid only for a 48 kHz microphone.
    """


def window_starts(n_samples: int, step: int) -> list[int]:
    """Return the start offsets of the analysis windows for one recording.

    Windows advance by ``step`` samples. When the last regular window ends
    before the recording does, one more window is aligned to the recording's
    end, so every sample is analysed at least once: a 10 s segment with 3 s
    windows and no overlap gets windows at 0, 3, 6 and 7 s. A recording
    shorter than one window gets a single zero-padded window, provided it
    holds at least ``MIN_CHUNK_SAMPLES``.

    Args:
        n_samples: Length of the recording in samples.
        step: Window advance in samples (window length minus overlap).

    Returns:
        Ascending window start offsets in samples.
    """
    if n_samples < MIN_CHUNK_SAMPLES:
        return []
    if n_samples <= WINDOW_SAMPLES:
        return [0]
    last_start = n_samples - WINDOW_SAMPLES
    starts = list(range(0, last_start + 1, step))
    if starts[-1] != last_start:
        starts.append(last_start)
    return starts


def is_contiguous(prev_start: datetime, prev_duration_s: float, start: datetime) -> bool:
    """Return whether a segment starts where the previous one of its device ended."""
    prev_end = prev_start + timedelta(seconds=prev_duration_s)
    return abs((start - prev_end).total_seconds()) <= CONTIGUITY_TOLERANCE_S


def read_tail(path: Path, n_samples: int) -> np.ndarray | None:
    """Read the last ``n_samples`` of a 48 kHz recording as mono float32.

    Returns ``None`` when the file is shorter or not at the model's rate.
    """
    info = sf.info(str(path))
    if info.samplerate != MODEL_SR or info.frames < n_samples:
        return None
    tail, _ = sf.read(str(path), start=info.frames - n_samples, dtype="float32")
    if tail.ndim > 1:
        tail = tail.mean(axis=1)
    return tail


def birdnet_week(moment: datetime) -> int:
    """Map a date to BirdNET's 48-week year (four weeks per month, 1-48).

    The meta-model's species list depends on the season, so the week comes
    from the recording's own timestamp, not from the time of analysis.
    """
    return (moment.month - 1) * 4 + min(3, (moment.day - 1) // 7) + 1


ANALYZER_KEY = "birdnet"


def _analysis_entry() -> Any:
    """This analyzer's entry in ``recordings.analysis_state``, as an SQL expression."""
    return func.json_extract(Recording.analysis_state, f"$.{ANALYZER_KEY}")


def _analysis_field(name: str) -> Any:
    """One field of this analyzer's entry, as an SQL expression."""
    return func.json_extract(Recording.analysis_state, f"$.{ANALYZER_KEY}.{name}")


def _flat_sigmoid(x: np.ndarray, sensitivity: float = 1.0) -> np.ndarray:
    """BirdNET sigmoid calculation (negative sensitivity matches birdnetlib/analyzer)."""
    res = 1.0 / (1.0 + np.exp(sensitivity * np.clip(x, -15, 15)))
    return res


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
            workspace_path=env_settings.WORKSPACE_DIR,
            redis_url=env_settings.REDIS_URL,
            heartbeat_interval=env_settings.HEARTBEAT_INTERVAL_S,
        )
        self.env_settings = env_settings
        self.birdnet_config: BirdnetSettings | None = None
        self.station_config: StationSettings | None = None
        self.model_version = _derive_model_version(MODEL_PATH.name)
        self.recordings_dir = Path(env_settings.RECORDINGS_DIR)

        self.clips_dir = Path(env_settings.WORKSPACE_DIR) / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Two-Phase Logging stats
        self.stats = BirdnetStats()

        # Snapshot Refresh: monitor birdnet tuning + station location (ADR-0031)
        self._config_sections = ["birdnet", "station"]
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
        from silvasonic.core.database.models.system import SettingsSection
        from sqlalchemy import select

        async with get_session() as session:
            stmt = select(SettingsSection).where(
                SettingsSection.section.in_(["birdnet", "station"])
            )
            result = await session.execute(stmt)
            configs = {row.section: row.value for row in result.scalars()}

            self.birdnet_config = BirdnetSettings(**configs.get("birdnet", {}))
            self.station_config = StationSettings(**configs.get("station", {}))

    def _get_allowed_species_mask(self, labels: list[str], week: int) -> tuple[np.ndarray, bool]:
        """Build the boolean mask of species plausible at the location in ``week``.

        Args:
            labels: Model labels, one per output class.
            week: BirdNET week (1-48) of the recordings the mask applies to.

        Returns:
            The mask and whether the location filter is active.
        """
        assert self.station_config is not None

        loc_filter_active = False
        allowed_mask = np.ones(len(labels), dtype=bool)

        if self.station_config.latitude is not None and self.station_config.longitude is not None:
            # We must run the meta-model to determine allowed species
            loc_filter_active = True
            try:
                meta_interp = Interpreter(model_path=str(META_MODEL_PATH), num_threads=1)
                meta_interp.allocate_tensors()
                meta_in = meta_interp.get_input_details()[0]["index"]
                meta_out = meta_interp.get_output_details()[0]["index"]

                meta_input = np.array(
                    [[self.station_config.latitude, self.station_config.longitude, week]],
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
                    week=week,
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
        week: int | None = None,
        lead_in_path: Path | None = None,
    ) -> list[Detection]:
        """Perform native inference on a single recording.

        ``week`` is the BirdNET week the species mask was built for; it is
        stored in each detection's details while the location filter is on.

        ``lead_in_path`` is the previous, contiguous segment of the same
        device. Its last 1.5 s are prepended, and one extra *seam window*
        spans the boundary, so a call cut in two by the segment split is
        analysed whole. A detection in the seam window starts up to 1.5 s
        before the recording does.
        """
        assert self.birdnet_config is not None
        assert self.station_config is not None

        loop = asyncio.get_running_loop()

        # Load audio blocking call bound to executor
        def _load() -> tuple[np.ndarray, np.ndarray]:
            audio, sr = sf.read(str(audio_path), dtype="float32")
            if sr != MODEL_SR:
                # Windows and timestamps would be scaled wrongly, the
                # detections meaningless
                raise UnsupportedSampleRateError(
                    f"{audio_path.name} is at {sr} Hz, the model expects {MODEL_SR} Hz"
                )
            if audio.ndim > 1:
                audio = audio.mean(axis=1)

            lead = None
            if lead_in_path is not None and len(audio) >= SEAM_SAMPLES:
                try:
                    lead = read_tail(lead_in_path, SEAM_SAMPLES)
                except Exception as e:  # the Janitor may have removed it meanwhile
                    log.debug("birdnet.lead_in_unreadable", path=str(lead_in_path), error=str(e))
            return audio, lead if lead is not None else np.zeros(0, dtype=np.float32)

        audio, lead = await loop.run_in_executor(None, _load)

        # Slice segments
        overlap = self.birdnet_config.overlap_s
        step = int((WINDOW_SECS - overlap) * MODEL_SR)

        detections: list[Detection] = []
        input_idx = interpreter.get_input_details()[0]["index"]
        output_idx = interpreter.get_output_details()[0]["index"]

        # Fast inversion for sigmoid according to spike v3
        adj_sens = max(0.5, min(1.0 - (self.birdnet_config.sensitivity - 1.0), 1.5))

        # Window offsets index the buffer: lead-in (if any) + the recording
        offset = len(lead)
        starts = [s + offset for s in window_starts(len(audio), step)]
        if offset:
            starts.insert(0, 0)  # the seam window, centred on the boundary
            audio = np.concatenate([lead, audio])

        for start_idx in starts:
            if self._shutdown_event.is_set():
                break

            chunk = audio[start_idx : start_idx + WINDOW_SAMPLES]
            if len(chunk) < WINDOW_SAMPLES:
                padded = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
                padded[: len(chunk)] = chunk
                chunk = padded

            # Inference
            def _infer(c: np.ndarray = chunk) -> np.ndarray:
                interpreter.set_tensor(input_idx, c.reshape(1, WINDOW_SAMPLES))
                interpreter.invoke()
                return interpreter.get_tensor(output_idx)[0]

            raw = await loop.run_in_executor(None, _infer)
            scores = _flat_sigmoid(raw, sensitivity=-adj_sens)

            # Mask and threshold filter
            mask = (scores >= self.birdnet_config.min_confidence) & allowed_mask
            hits = np.where(mask)[0]

            w_start_td = timedelta(seconds=(start_idx - offset) / MODEL_SR)
            w_end_td = w_start_td + timedelta(seconds=WINDOW_SECS)

            for i in hits:
                score = float(scores[i])
                parts = labels[i].split("_")

                label_basename = f"{parts[0]}_{parts[1]}" if len(parts) > 1 else parts[0]

                details = BirdnetDetectionDetails(
                    model_version=self.model_version,
                    sensitivity=self.birdnet_config.sensitivity,
                    overlap_s=self.birdnet_config.overlap_s,
                    min_confidence=self.birdnet_config.min_confidence,
                    location_filter_active=loc_filter_active,
                    lat=self.station_config.latitude,
                    lon=self.station_config.longitude,
                    week=week if loc_filter_active else None,
                )

                # Extraction: Create a WAV file clip
                start_ms = int(w_start_td.total_seconds() * 1000)
                end_ms = int(w_end_td.total_seconds() * 1000)

                safe_label = re.sub(r"[^a-zA-Z0-9]", "", label_basename)
                clip_filename = f"{recording.id}_{start_ms}_{end_ms}_{safe_label}.wav"

                clip_path = self.clips_dir / clip_filename

                # Audio slicing logic: ± clip_padding_s
                pad_samples = int(self.birdnet_config.clip_padding_s * MODEL_SR)
                slice_start = max(0, start_idx - pad_samples)
                slice_end = min(len(audio), start_idx + WINDOW_SAMPLES + pad_samples)

                # Write audio inside executor, with IO try/except
                def _write_clip(
                    s_start: int = slice_start,
                    s_end: int = slice_end,
                    dest: Path = clip_path,
                    aud: np.ndarray = audio,
                ) -> bool:
                    try:
                        sf.write(str(dest), aud[s_start:s_end], MODEL_SR)
                        return True
                    except Exception as e:
                        log.warning("birdnet.clip_extraction_failed", error=str(e), path=str(dest))
                        return False

                written = await loop.run_in_executor(None, _write_clip)
                det_clip_path = f"clips/{clip_filename}" if written else None

                det = Detection(
                    recording_id=recording.id,
                    analyzer="birdnet",
                    started_at=recording.started_at + w_start_td,
                    ended_at=recording.started_at + w_end_td,
                    label=label_basename,
                    species_id=label_species_id(label_basename),
                    confidence=score,
                    details=details.model_dump(),
                    clip_path=det_clip_path,
                )
                detections.append(det)

        # Explicit memory cleanup
        del audio
        gc.collect()

        return detections

    async def _previous_segment_path(
        self, session: AsyncSession, recording: Recording
    ) -> Path | None:
        """Return the file of the segment right before ``recording``, if contiguous.

        Same device, ending where ``recording`` starts, still on disk.  A gap
        (FFmpeg restart, device unplugged) or a deleted file yields ``None``.
        """
        result = await session.execute(
            select(
                Recording.started_at,
                Recording.duration_s,
                Recording.processed_path,
                Recording.raw_path,
            )
            .where(Recording.microphone_id == recording.microphone_id)
            .where(Recording.started_at < recording.started_at)
            .where(Recording.deleted_at.is_(None))
            .order_by(Recording.started_at.desc())
            .limit(1)
        )
        prev = result.first()
        if prev is None or not is_contiguous(
            prev.started_at, prev.duration_s, recording.started_at
        ):
            return None
        path = self.recordings_dir / (prev.processed_path or prev.raw_path)
        return path if path.exists() else None

    async def _claim_next_recording(self) -> Recording | None:
        """Claim the next recording to analyse, in one short transaction.

        The claim (``AnalysisClaim``) is committed before inference starts, so
        the database is free while the model runs (ADR-0037).  A claim older
        than ``CLAIM_LEASE`` belongs to a worker that died and is taken over.
        """
        assert self.birdnet_config is not None
        now = datetime.now(UTC)
        entry = _analysis_entry()
        order = (
            Recording.started_at.desc()
            if self.birdnet_config.processing_order == "newest_first"
            else Recording.started_at.asc()
        )
        candidate = (
            select(Recording.id)
            .where(Recording.deleted_at.is_(None))
            .where(
                or_(
                    entry.is_(None),
                    and_(
                        _analysis_field("state") == "running",
                        _analysis_field("claimed_at") < AnalysisClaim.timestamp(now - CLAIM_LEASE),
                    ),
                )
            )
            .order_by(order)
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            update(Recording)
            .where(Recording.id == candidate)
            .values(
                analysis_state=func.json_set(
                    Recording.analysis_state,
                    f"$.{ANALYZER_KEY}",
                    func.json(AnalysisClaim.at(now).to_json_text()),
                )
            )
            .returning(Recording)
            .execution_options(synchronize_session=False)
        )
        async with get_session() as session:
            recording = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
        return recording

    async def _finish_recording(
        self,
        recording_id: object,
        state: AnalysisState,
        detections: list[Detection] | None = None,
    ) -> None:
        """Store the detections and the result of one recording, in one transaction.

        Only this analyzer's entry in ``analysis_state`` changes.
        """
        async with get_session() as session:
            if detections:
                session.add_all(detections)
            await session.execute(
                update(Recording)
                .where(Recording.id == recording_id)
                .values(
                    analysis_state=func.json_set(
                        Recording.analysis_state,
                        f"$.{ANALYZER_KEY}",
                        func.json(json.dumps(state.to_json())),
                    )
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()

    async def run(self) -> None:
        """Main inference loop."""
        assert self.birdnet_config is not None, "BirdNET DB config not loaded"
        assert self.station_config is not None, "Station DB config not loaded"

        self.health.update_status("birdnet", True, "initializing native engine")

        try:
            with open(LABELS_PATH) as f:
                labels = [line.strip() for line in f.readlines()]

            interpreter = Interpreter(
                model_path=str(MODEL_PATH), num_threads=self.birdnet_config.thread_count
            )
            interpreter.allocate_tensors()

        except Exception as e:
            log.error("birdnet.init_failed", error=str(e))
            self.health.update_status("birdnet", False, str(e))
            await asyncio.sleep(5)
            # Crash fast
            return

        self.health.update_status("birdnet", True, "idle")

        # Species masks by BirdNET week, valid for the current location only.
        species_masks: dict[int, tuple[np.ndarray, bool]] = {}

        while not self._shutdown_event.is_set():
            self.health.touch()
            self.stats.maybe_emit_summary()

            # --- Snapshot Refresh: reload tuning parameters (ADR-0031) ---
            prev_lat = self.station_config.latitude if self.station_config else None
            prev_lon = self.station_config.longitude if self.station_config else None
            await self._refresh_config()
            # A new location invalidates every cached species mask
            if self.station_config and (
                self.station_config.latitude != prev_lat
                or self.station_config.longitude != prev_lon
            ):
                species_masks.clear()
                log.info(
                    "birdnet.species_masks_reset",
                    lat=self.station_config.latitude,
                    lon=self.station_config.longitude,
                )

            # Backlog update (for heartbeat meta)
            try:
                async with get_session() as session:
                    count_result = await session.execute(
                        select(func.count())
                        .select_from(Recording)
                        .where(Recording.deleted_at.is_(None))
                        .where(_analysis_entry().is_(None))
                    )
                    self._backlog_pending = count_result.scalar_one()
            except Exception:
                pass  # Best-effort — keep last known value

            try:
                self.health.update_status("birdnet", True, "polling")

                recording = await self._claim_next_recording()
                if recording is None:
                    # No work found, sleep
                    await asyncio.sleep(self.env_settings.POLLING_INTERVAL_S)
                    continue

                # Check file existence — DB stores relative paths, prefix with recordings_dir
                rel_path = recording.processed_path or recording.raw_path
                audio_path = self.recordings_dir / rel_path
                if not audio_path.exists():
                    log.error("birdnet.file_missing", path=str(audio_path))
                    # Mark as failed in DB to prevent infinite loop
                    await self._finish_recording(
                        recording.id, AnalysisState.failed(REASON_FILE_MISSING)
                    )
                    continue

                # Process — no database transaction is open while the model runs
                self.health.update_status("birdnet", True, f"analyzing {recording.id}")
                start_time = time.perf_counter()

                try:
                    week = birdnet_week(recording.started_at)
                    if week not in species_masks:
                        species_masks[week] = self._get_allowed_species_mask(labels, week)
                    allowed_mask, loc_filter_active = species_masks[week]
                    async with get_session() as session:
                        lead_in_path = await self._previous_segment_path(session, recording)

                    detections = await self._process_recording(
                        recording,
                        audio_path,
                        interpreter,
                        labels,
                        allowed_mask,
                        loc_filter_active,
                        week,
                        lead_in_path,
                    )

                    if detections:
                        await register_species({d.label for d in detections})
                    await self._finish_recording(
                        recording.id, AnalysisState.done(len(detections)), detections
                    )
                    elapsed = time.perf_counter() - start_time
                    self.stats.record_analyzed(recording.id, elapsed, len(detections))

                except UnsupportedSampleRateError as e:
                    log.warning(
                        "birdnet.unsupported_sample_rate",
                        recording_id=recording.id,
                        error=str(e),
                    )
                    await self._finish_recording(
                        recording.id, AnalysisState.skipped(REASON_SAMPLE_RATE_UNSUPPORTED)
                    )

                except Exception as e:
                    self.stats.record_error(recording.id, e)
                    # Store the failure in state; the error text is in the log
                    await self._finish_recording(recording.id, AnalysisState.failed())

            except Exception as exc:
                # Soft-fail transient DB errors or post-rollback persistence failures (ADR-0030)
                log.warning("birdnet.db_cycle_failed", error=str(exc))
                self.health.update_status("birdnet", False, "database_unavailable")
                await asyncio.sleep(self.env_settings.DB_RETRY_INTERVAL_S)
                continue

        # Emit final summary on shutdown
        self.stats.emit_final_summary()
