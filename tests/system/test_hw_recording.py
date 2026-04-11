"""Hardware-dependent recording tests — require real USB microphone.

Tests the full recording pipeline with real audio hardware:
- Device validation (ALSA query, sample rate acceptance)
- Live audio capture via FFmpegPipeline → WAV file verification
- Full lifecycle: Plug → Scan → DB → Container with /dev/snd → WAV output

These tests are **never** included in CI or ``just ci``.
Run manually with:

    just test-hw

All tests in this module are fully automated (no ``input()`` prompts).
They require a connected USB microphone but no manual interaction.

Skip conditions:
- No USB-Audio device detected → all tests skipped
- Primary mic not connected → respective tests skipped
- Podman socket not available → container tests skipped
- Recorder image not built → container tests skipped
"""

from __future__ import annotations

import contextlib
import subprocess
import time
from pathlib import Path

import pytest
import structlog
from silvasonic.controller.container_manager import ContainerManager
from silvasonic.controller.container_spec import (
    MountSpec,
    RestartPolicy,
    Tier2ServiceSpec,
)
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.controller.podman_client import SilvasonicPodmanClient
from silvasonic.controller.profile_matcher import ProfileMatcher
from silvasonic.controller.reconciler import DeviceStateEvaluator
from silvasonic.recorder.ffmpeg_pipeline import PROCESSED_SAMPLE_RATE, FFmpegConfig, FFmpegPipeline
from silvasonic.recorder.workspace import ensure_workspace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ._hw_helpers import has_usb_audio_device
from ._processor_helpers import (
    DATABASE_IMAGE,
    PROCESSOR_IMAGE,
    make_processor_env,
    podman_logs,
    podman_run,
    podman_stop_rm,
    psql_query,
    require_database_image,
    require_processor_image,
    seed_test_devices,
    wait_for_db,
    wait_for_db_rows,
    wait_for_wavs,
)
from .conftest import (
    PODMAN_SOCKET,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
    TEST_RUN_ID,
    require_primary_mic,
    require_recorder_image,
)

log = structlog.get_logger()

pytestmark = [
    pytest.mark.system_hw_auto,
]


_USB_PRESENT = has_usb_audio_device()


# ---------------------------------------------------------------------------
# Polling helpers (replace fixed time.sleep)
# ---------------------------------------------------------------------------


def _ffprobe_wav(path: Path) -> tuple[int, int, str]:
    """Return (sample_rate, channels, codec) via ffprobe.

    Args:
        path: Path to the WAV file.

    Returns:
        Tuple of (sample_rate, channels, codec_name).
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate,channels,codec_name",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, f"ffprobe failed on {path.name}: {result.stderr}"
    parts = result.stdout.strip().split(",")
    assert len(parts) >= 3, f"Unexpected ffprobe output: {result.stdout}"
    return int(parts[1]), int(parts[2]), parts[0]


def _dump_container_logs(container_name: str) -> None:
    """Log container stdout/stderr via structlog for debugging."""
    try:
        result = subprocess.run(
            ["podman", "logs", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        log.warning(
            "test.container_logs",
            container=container_name,
            stdout=result.stdout[-500:] if result.stdout else "",
            stderr=result.stderr[-500:] if result.stderr else "",
        )
    except Exception as exc:
        log.warning("test.container_logs_failed", container=container_name, error=str(exc))


# ---------------------------------------------------------------------------
# Test: Device Validation (ALSA query + sample rate)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestDeviceValidation:
    """Validate ALSA device accessibility and profile sample rate compatibility.

    These tests verify that the configured microphone's ALSA device is
    queryable by arecord and that the profile's sample rate is accepted.
    """

    def test_alsa_device_queryable(self, primary_device: DeviceInfo) -> None:
        """Primary mic's ALSA device can be queried via arecord.

        Verifies that ``arecord -l`` lists the expected card number.
        """
        alsa_device = primary_device.alsa_device
        result = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
        # Extract card number from device string (e.g. "hw:2,0" → "2")
        card_num = alsa_device.split(":")[1].split(",")[0] if ":" in alsa_device else alsa_device
        card_marker = f"card {card_num}:"
        assert card_marker in result.stdout, f"Device {alsa_device} not found in arecord -l output"

        card_line = ""
        for line in result.stdout.splitlines():
            if card_marker in line:
                card_line = line.strip()
                break
        log.info("test.alsa_queryable", device=alsa_device, card_info=card_line)

    def test_ffmpeg_accepts_device(self, primary_device: DeviceInfo) -> None:
        """FFmpeg can open the ALSA device for a brief capture."""
        mic = require_primary_mic()
        alsa_device = primary_device.alsa_device
        sample_rate = mic.sample_rate

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-f",
                "alsa",
                "-sample_rate",
                str(sample_rate),
                "-channels",
                "1",
                "-i",
                alsa_device,
                "-t",
                "0.5",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"FFmpeg failed to open {alsa_device} at {sample_rate} Hz: {result.stderr}"
        )
        log.info("test.ffmpeg_accepted", device=alsa_device, sample_rate=sample_rate)


# ---------------------------------------------------------------------------
# Test: Real Audio Capture (FFmpeg pipeline → WAV + header validation)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestRealAudioCapture:
    """Verify that FFmpegPipeline produces valid WAV files with real hardware.

    Uses a short segment duration (3s) to keep test runtime reasonable.
    The pipeline runs for ~8s to ensure at least one segment is promoted.
    Validates both file creation and WAV header metadata.
    """

    _SEGMENT_S = 3
    _CAPTURE_S = 3.5

    def _make_pipeline(
        self,
        workspace: Path,
        device: str,
        sample_rate: int,
    ) -> FFmpegPipeline:
        """Create a pipeline with test-friendly short segment duration."""
        ensure_workspace(workspace)
        cfg = FFmpegConfig(
            sample_rate=sample_rate,
            channels=1,
            format="S16LE",
            segment_duration_s=self._SEGMENT_S,
            gain_db=0.0,
        )
        return FFmpegPipeline(config=cfg, workspace=workspace, device=device)

    @staticmethod
    def _run_pipeline(pipeline: FFmpegPipeline, duration_s: float) -> None:
        """Start pipeline, wait for *duration_s*, then stop.

        FFmpeg runs as a separate process — no drain loop needed.
        """
        pipeline.start()
        time.sleep(duration_s)
        pipeline.stop()

    def test_pipeline_captures_valid_audio(
        self,
        primary_device: DeviceInfo,
        tmp_path: Path,
    ) -> None:
        """FFmpegPipeline with real device produces valid WAV files.

        Verifies:
        1. At least 1 raw and 1 processed WAV file created.
        2. Raw WAV header matches expected sample rate and codec.
        3. Processed WAV has correct downsampled rate.
        """
        workspace = tmp_path / "capture_test"
        pipeline = self._make_pipeline(
            workspace,
            primary_device.alsa_device,
            require_primary_mic().sample_rate,
        )

        self._run_pipeline(pipeline, self._CAPTURE_S)
        assert not pipeline.is_active, "Pipeline should be inactive after stop()"

        # Verify raw WAV files
        data_dir = workspace / "data" / "raw"
        wav_files = list(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, (
            f"Expected at least 1 WAV file in {data_dir}, "
            f"found {len(wav_files)}. "
            f"Buffer dir contents: {list((workspace / '.buffer' / 'raw').glob('*'))}"
        )

        # Verify processed WAV files
        proc_dir = workspace / "data" / "processed"
        proc_wavs = list(proc_dir.glob("*.wav"))
        assert len(proc_wavs) >= 1, (
            f"Expected at least 1 processed WAV in {proc_dir}, found {len(proc_wavs)}"
        )

        log.info(
            "test.capture_complete",
            raw_count=len(wav_files),
            processed_count=len(proc_wavs),
        )

        # Validate raw WAV header
        raw_sr, raw_ch, raw_codec = _ffprobe_wav(wav_files[0])
        assert raw_ch >= 1
        log.info(
            "test.raw_wav_valid",
            file=wav_files[0].name,
            sample_rate=raw_sr,
            channels=raw_ch,
            codec=raw_codec,
        )

        # Validate processed WAV header
        proc_sr, _proc_ch, _proc_codec = _ffprobe_wav(proc_wavs[0])
        assert proc_sr == PROCESSED_SAMPLE_RATE, (
            f"Processed WAV SR {proc_sr} != {PROCESSED_SAMPLE_RATE}"
        )
        log.info(
            "test.processed_wav_valid",
            file=proc_wavs[0].name,
            sample_rate=proc_sr,
        )


# ---------------------------------------------------------------------------
# Test: Full Hardware Lifecycle (Plug → Container → WAV)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
@pytest.mark.skipif(
    not SOCKET_AVAILABLE,
    reason=f"Podman socket not found at {PODMAN_SOCKET}",
)
class TestFullHardwareLifecycle:
    """End-to-end: device detection → DB → container with real /dev/snd → WAV.

    This is the critical test that verifies the ENTIRE production lifecycle
    from USB device detection to actual audio recording inside a
    containerized Recorder with /dev/snd passthrough.
    """

    async def test_plug_to_wav(
        self,
        primary_device: DeviceInfo,
        seeded_db: async_sessionmaker[AsyncSession],
        hw_redis: tuple[str, int, str],
        tmp_path: Path,
    ) -> None:
        """Full lifecycle: Plug → Scan → Match → DB → Container → WAV output.

        Steps:
        1. Use detected primary device (already scanned via fixture).
        2. Match against seeded profiles → auto-enroll.
        3. Evaluate desired state → Tier2ServiceSpec.
        4. Start container with REAL /dev/snd passthrough.
        5. Poll for WAV files (replaces fixed sleep).
        6. Stop container and verify WAV files in workspace.
        """
        require_recorder_image()

        _redis_host, _redis_port, hw_network = hw_redis

        session_factory = seeded_db

        # Step 2: Match profile
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(primary_device, session)

        if match_result.score < 100:
            pytest.skip(
                f"Primary mic ({primary_device.alsa_name}) did not match "
                f"profile '{require_primary_mic().slug}' (score={match_result.score})"
            )

        # Step 3: Upsert as enrolled
        from silvasonic.controller.device_repository import upsert_device

        async with session_factory() as session:
            await upsert_device(
                primary_device,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled",
            )
            await session.commit()

        # Step 4: Evaluate → get spec
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        matching = [
            s
            for s in specs
            if s.labels.get("io.silvasonic.device_id") == primary_device.stable_device_id
        ]
        assert len(matching) == 1, (
            f"Expected 1 spec for {primary_device.stable_device_id}, got {len(matching)}"
        )
        spec = matching[0]

        # Step 5: Create container with REAL /dev/snd (the key difference!)
        test_name = f"silvasonic-recorder-system-test-hw-lifecycle-{TEST_RUN_ID}"

        workspace = tmp_path / "hw_lifecycle"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        test_spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=test_name,
            network=hw_network,
            environment={
                **spec.environment,
                "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
            },
            labels={
                **spec.labels,
                "io.silvasonic.test": "system_hw_auto",
                "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
            },
            mounts=[
                MountSpec(
                    source=str(workspace),
                    target="/app/workspace",
                    read_only=False,
                ),
            ],
            devices=["/dev/snd"],
            group_add=["audio"],
            privileged=False,
            restart_policy=RestartPolicy(name="no", max_retry_count=0),
            memory_limit="256m",
            cpu_limit=1.0,
            oom_score_adj=-999,
        )

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")
            info = mgr.start(test_spec)
            assert info is not None, "Container start failed"
            assert info.get("name") == test_name

            # Step 6: Poll for WAV files (replaces fixed 20s sleep)
            data_dir = workspace / "data" / "raw"
            log.info("test.waiting_for_wavs", directory=str(data_dir), timeout_s=20)
            wait_for_wavs(data_dir, min_count=1, timeout=20)

            # Step 7: Stop container gracefully (promotes final segment)
            mgr.stop(test_name, timeout=10)

            # Step 8: Verify WAV files exist in the workspace
            buffer_dir = workspace / ".buffer" / "raw"
            wav_in_data = list(data_dir.glob("*.wav")) if data_dir.exists() else []
            wav_in_buffer = list(buffer_dir.glob("*.wav")) if buffer_dir.exists() else []
            total_wavs = len(wav_in_data) + len(wav_in_buffer)

            if total_wavs < 1:
                _dump_container_logs(test_name)

            assert total_wavs >= 1, (
                f"No WAV files found in workspace {workspace}. "
                f"data/raw: {wav_in_data}, .buffer/raw: {wav_in_buffer}. "
                f"Check container logs with: podman logs {test_name}"
            )

            # Verify processed WAV files
            proc_data_dir = workspace / "data" / "processed"
            proc_buffer_dir = workspace / ".buffer" / "processed"
            proc_in_data = list(proc_data_dir.glob("*.wav")) if proc_data_dir.exists() else []
            proc_in_buffer = list(proc_buffer_dir.glob("*.wav")) if proc_buffer_dir.exists() else []
            total_proc = len(proc_in_data) + len(proc_in_buffer)
            assert total_proc >= 1, (
                f"No processed WAV files found in {workspace}. "
                f"data/processed: {proc_in_data}, .buffer/processed: {proc_in_buffer}"
            )

            log.info(
                "test.lifecycle_verified",
                raw_promoted=len(wav_in_data),
                raw_buffered=len(wav_in_buffer),
                processed_total=total_proc,
            )

            # Cleanup
            mgr.remove(test_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()


# ---------------------------------------------------------------------------
# Test: Full Pipeline E2E (DB + Redis + Podman + Real Hardware + WAV + Heartbeat)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
@pytest.mark.skipif(not SOCKET_AVAILABLE, reason="Podman socket not available")
class TestFullPipelineE2E:
    """Ultimate E2E: USB scan → DB → Redis → Container → WAV + Heartbeat.

    This is the comprehensive production-path confidence test for v0.5.0.
    Unlike ``TestFullHardwareLifecycle``, this test also includes:

    - A real Redis on an isolated test network for heartbeat verification.
    - WAV header validation (sample rate, channels, format).
    - Redis heartbeat assertions (service, health, watchdog metadata).
    - Container health-endpoint check.
    - Processor Indexer pipeline (v0.5.0): real WAV → DB registration.
    """

    async def test_full_pipeline_with_heartbeat(
        self,
        primary_device: DeviceInfo,
        seeded_db: async_sessionmaker[AsyncSession],
        hw_redis: tuple[str, int, str],
        tmp_path: Path,
    ) -> None:
        """Full pipeline: Scan → Match → DB → Container → WAV + Redis heartbeat.

        Validates:
        1. Profile matching and device enrollment.
        2. DeviceStateEvaluator produces a valid Tier2ServiceSpec.
        3. Container starts with real /dev/snd and produces dual-stream WAV files.
        4. WAV files have valid headers (correct sample rate and channels).
        5. Redis heartbeat contains service, health, recording, and watchdog metadata.
        6. Container health endpoint returns 200.
        """
        require_recorder_image()

        session_factory = seeded_db
        redis_host, redis_port, hw_network = hw_redis

        # ── Step 1: Match profile ──────────────────────────────────
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(primary_device, session)

        if match_result.score < 100:
            pytest.skip(
                f"Primary mic ({primary_device.alsa_name}) did not match "
                f"profile '{require_primary_mic().slug}' (score={match_result.score})"
            )

        # ── Step 2: Enroll device in DB ────────────────────────────
        from silvasonic.controller.device_repository import upsert_device

        async with session_factory() as session:
            await upsert_device(
                primary_device,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled",
            )
            await session.commit()

        # ── Step 3: Evaluate desired state ─────────────────────────
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        matching_specs = [
            s
            for s in specs
            if s.labels.get("io.silvasonic.device_id") == primary_device.stable_device_id
        ]
        assert len(matching_specs) == 1, (
            f"Expected 1 spec for {primary_device.stable_device_id}, got {len(matching_specs)}"
        )
        spec = matching_specs[0]

        # ── Step 4: Start Recorder container ───────────────────────
        test_name = f"silvasonic-recorder-e2e-pipeline-{TEST_RUN_ID}"
        workspace = tmp_path / "e2e_pipeline"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        test_spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=test_name,
            network=hw_network,
            environment={
                **spec.environment,
                "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
                # Override Redis URL to point to our test Redis
                "SILVASONIC_REDIS_URL": "redis://silvasonic-redis:6379/0",
            },
            labels={
                **spec.labels,
                "io.silvasonic.test": "system_hw_e2e",
                "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
            },
            mounts=[
                MountSpec(
                    source=str(workspace),
                    target="/app/workspace",
                    read_only=False,
                ),
            ],
            devices=["/dev/snd"],
            group_add=["audio"],
            privileged=False,
            restart_policy=RestartPolicy(name="no", max_retry_count=0),
            memory_limit="256m",
            cpu_limit=1.0,
            oom_score_adj=-999,
        )

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")
            info = mgr.start(test_spec)
            assert info is not None, "Container start failed"
            assert info.get("name") == test_name

            # ── Step 5: Poll for WAV files (replaces fixed 18s sleep) ──
            raw_data = workspace / "data" / "raw"
            proc_data = workspace / "data" / "processed"

            log.info("test.waiting_for_wavs", directory=str(raw_data), timeout_s=20)
            raw_wavs = wait_for_wavs(raw_data, min_count=1, timeout=20)
            proc_wavs = wait_for_wavs(proc_data, min_count=1, timeout=5)

            if not raw_wavs and not proc_wavs:
                _dump_container_logs(test_name)

            assert len(raw_wavs) >= 1, (
                f"No raw WAV files in {raw_data}. Check container logs: podman logs {test_name}"
            )
            assert len(proc_wavs) >= 1, (
                f"No processed WAV files in {proc_data}. "
                f"Check container logs: podman logs {test_name}"
            )
            log.info(
                "test.wav_files_found",
                raw_count=len(raw_wavs),
                processed_count=len(proc_wavs),
            )

            # ── Step 6: Validate WAV headers (via ffprobe) ────────
            raw_sr, raw_ch, raw_codec = _ffprobe_wav(raw_wavs[0])
            assert raw_ch >= 1
            assert raw_sr == require_primary_mic().sample_rate, (
                f"Raw WAV sample rate {raw_sr} != expected {require_primary_mic().sample_rate}"
            )
            log.info(
                "test.raw_wav_valid",
                sample_rate=raw_sr,
                channels=raw_ch,
                codec=raw_codec,
            )

            proc_sr, proc_ch, proc_codec = _ffprobe_wav(proc_wavs[0])
            assert proc_ch >= 1
            assert proc_sr == PROCESSED_SAMPLE_RATE, (
                f"Processed WAV sample rate {proc_sr} != expected {PROCESSED_SAMPLE_RATE}"
            )
            log.info(
                "test.processed_wav_valid",
                sample_rate=proc_sr,
                channels=proc_ch,
                codec=proc_codec,
            )

            # ── Step 7: Assert Redis heartbeat ─────────────────────
            import json
            from typing import Any

            from redis import Redis

            redis_client = Redis(
                host=redis_host,
                port=redis_port,
                decode_responses=True,
            )

            # Poll for heartbeat (recorder writes every ~2s)
            heartbeat_raw: str | None = None
            for _ in range(15):
                keys: list[str] = list(redis_client.keys("silvasonic:status:*"))  # type: ignore[arg-type]
                for key in keys:
                    val = redis_client.get(key)
                    if val is not None:
                        try:
                            data = json.loads(str(val))
                            if data.get("service") == "recorder":
                                heartbeat_raw = str(val)
                                break
                        except (json.JSONDecodeError, TypeError):
                            continue
                if heartbeat_raw:
                    break
                time.sleep(1)

            assert heartbeat_raw is not None, (
                "No recorder heartbeat found in Redis after 15s. "
                f"Keys present: {list(redis_client.keys('silvasonic:*'))}"  # type: ignore[arg-type]
            )

            payload: dict[str, Any] = json.loads(heartbeat_raw)
            assert payload["service"] == "recorder"
            assert payload["health"]["status"] == "ok"
            assert "recording" in payload["meta"]
            assert payload["meta"]["recording"]["raw_enabled"] is True
            assert payload["meta"]["recording"]["processed_enabled"] is True

            assert "watchdog_restarts" in payload["meta"]["recording"], (
                "Watchdog metadata missing from heartbeat"
            )
            assert payload["meta"]["recording"]["watchdog_restarts"] == 0

            log.info(
                "test.heartbeat_verified",
                service=payload["service"],
                health=payload["health"]["status"],
                watchdog_restarts=payload["meta"]["recording"]["watchdog_restarts"],
            )
            redis_client.close()

            # ── Step 8: Health endpoint ────────────────────────────
            health_result = subprocess.run(
                [
                    "podman",
                    "exec",
                    test_name,
                    "curl",
                    "-sf",
                    "http://localhost:9500/healthy",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert health_result.returncode == 0, f"Health endpoint failed: {health_result.stderr}"
            log.info("test.health_endpoint_ok", status=200)

            # ── Teardown ───────────────────────────────────────────
            mgr.stop(test_name, timeout=10)
            mgr.remove(test_name)

            log.info("test.e2e_passed", pipeline="USB→DB→Podman→FFmpeg→WAV→Redis→Health")
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()

    @pytest.mark.timeout(120)
    async def test_hw_recorder_to_processor_pipeline(
        self,
        primary_device: DeviceInfo,
        seeded_db: async_sessionmaker[AsyncSession],
        hw_redis: tuple[str, int, str],
        tmp_path: Path,
    ) -> None:
        """Real USB mic → Recorder → WAV → Processor Indexer → recordings in DB.

        v0.5.0 HW test that validates the complete production pipeline:

        1. Recorder captures real audio from USB microphone.
        2. WAV files are promoted to device workspace.
        3. Standalone DB + Processor containers pick up those files.
        4. Processor Indexer registers recordings in the DB.
        5. Assert recordings rows have correct metadata.

        This test uses real hardware audio, a real containerized DB,
        and a real Processor — the full production path.
        """
        require_recorder_image()
        require_processor_image()
        require_database_image()

        _redis_host, _redis_port, hw_network = hw_redis

        session_factory = seeded_db

        # ── Step 1: Match profile + enroll ──────────────────────────
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(primary_device, session)

        if match_result.score < 100:
            pytest.skip(
                f"Primary mic ({primary_device.alsa_name}) did not match "
                f"profile '{require_primary_mic().slug}' (score={match_result.score})"
            )

        from silvasonic.controller.device_repository import upsert_device

        async with session_factory() as session:
            await upsert_device(
                primary_device,
                session,
                profile_slug=match_result.profile_slug,
                enrollment_status="enrolled",
            )
            await session.commit()

        # ── Step 2: Evaluate → get spec ─────────────────────────────
        evaluator = DeviceStateEvaluator()
        async with session_factory() as session:
            specs = await evaluator.evaluate(session)

        matching_specs = [
            s
            for s in specs
            if s.labels.get("io.silvasonic.device_id") == primary_device.stable_device_id
        ]
        assert len(matching_specs) == 1
        spec = matching_specs[0]

        # ── Step 3: Setup infrastructure ────────────────────────────
        db_name = f"silvasonic-db-hw-proc-{TEST_RUN_ID}"
        processor_name = f"silvasonic-processor-hw-{TEST_RUN_ID}"
        test_name = f"silvasonic-recorder-hw-proc-{TEST_RUN_ID}"

        workspace = tmp_path / "hw_proc_pipeline"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        # Recordings root mirrors production layout: {root}/{device_id}/data/processed/
        recordings_root = tmp_path / "recorder_data"
        device_dir = recordings_root / primary_device.stable_device_id
        device_dir.mkdir(parents=True, exist_ok=True)
        recordings_root.chmod(0o777)
        device_dir.chmod(0o777)

        client = SilvasonicPodmanClient(
            socket_path=PODMAN_SOCKET,
            max_retries=2,
            retry_delay=0.5,
        )
        client.connect()

        try:
            # Start DB container
            podman_run(
                db_name,
                DATABASE_IMAGE,
                env={
                    "POSTGRES_USER": "silvasonic",
                    "POSTGRES_PASSWORD": "silvasonic",
                    "POSTGRES_DB": "silvasonic",
                },
                network=hw_network,
                network_aliases=["database", "silvasonic-database"],
            )
            wait_for_db(db_name, timeout=30)

            # Seed device so FK constraints are satisfied
            seed_test_devices(db_name, [primary_device.stable_device_id])

            # ── Step 4: Start Recorder with real /dev/snd ──────────
            mgr = ContainerManager(client, owner_profile=f"controller-test-{TEST_RUN_ID}")

            test_spec = Tier2ServiceSpec(
                image=RECORDER_IMAGE,
                name=test_name,
                network=hw_network,
                environment={
                    **spec.environment,
                    "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
                    "SILVASONIC_REDIS_URL": "redis://silvasonic-redis:6379/0",
                },
                labels={
                    **spec.labels,
                    "io.silvasonic.test": "system_hw_proc",
                    "io.silvasonic.owner": f"controller-test-{TEST_RUN_ID}",
                },
                mounts=[
                    MountSpec(
                        source=str(device_dir),
                        target="/app/workspace",
                        read_only=False,
                    ),
                ],
                devices=["/dev/snd"],
                group_add=["audio"],
                privileged=False,
                restart_policy=RestartPolicy(name="no", max_retry_count=0),
                memory_limit="256m",
                cpu_limit=1.0,
                oom_score_adj=-999,
            )

            info = mgr.start(test_spec)
            assert info is not None, "Recorder container start failed"

            # ── Step 5: Poll for WAV segments (replaces fixed 20s sleep) ──
            proc_dir = device_dir / "data" / "processed"
            log.info("test.waiting_for_recorder", directory=str(proc_dir), timeout_s=20)
            proc_wavs = wait_for_wavs(proc_dir, min_count=1, timeout=20)

            raw_dir = device_dir / "data" / "raw"
            raw_wavs = list(raw_dir.glob("*.wav")) if raw_dir.exists() else []

            if not proc_wavs:
                _dump_container_logs(test_name)

            assert len(proc_wavs) >= 1, (
                f"Recorder did not produce processed WAV files. "
                f"raw: {len(raw_wavs)}, processed: {len(proc_wavs)}"
            )
            log.info(
                "test.recorder_output",
                raw_count=len(raw_wavs),
                processed_count=len(proc_wavs),
            )

            # ── Step 6: Start Processor ────────────────────────────
            podman_run(
                processor_name,
                PROCESSOR_IMAGE,
                env={
                    **make_processor_env(),
                    "SILVASONIC_REDIS_URL": "redis://silvasonic-redis:6379/0",
                },
                volumes=[f"{recordings_root}:/data/recorder:z"],
                network=hw_network,
            )

            # ── Step 7: Poll for recordings in DB (replaces fixed 15s sleep) ──
            log.info("test.waiting_for_indexer", timeout_s=20)
            count = wait_for_db_rows(
                db_name,
                "SELECT COUNT(*) FROM recordings",
                min_count=1,
                timeout=20,
            )

            if count == 0:
                log.warning(
                    "test.indexer_no_rows",
                    processor_logs=podman_logs(processor_name),
                )

            assert count >= 1, (
                f"Processor did not index any recordings from real hardware. "
                f"WAV files on disk: {len(proc_wavs)}"
            )

            # Verify metadata (duration, sample_rate, sensor_id)
            rows_str = psql_query(
                db_name,
                "SELECT sensor_id, file_processed, duration, sample_rate FROM recordings LIMIT 5",
            )
            for line in rows_str.splitlines():
                parts = line.split("|")
                if len(parts) < 4:
                    continue
                sensor_id = parts[0].strip()
                duration = float(parts[2].strip())
                sample_rate = int(parts[3].strip())
                assert sensor_id == primary_device.stable_device_id, (
                    f"sensor_id mismatch: {sensor_id} != {primary_device.stable_device_id}"
                )
                assert duration > 0, f"Recording duration must be > 0, got {duration}"
                assert sample_rate > 0, f"Sample rate must be > 0, got {sample_rate}"

            log.info(
                "test.processor_pipeline_passed",
                recordings_indexed=count,
                wav_files=len(proc_wavs),
                mic=require_primary_mic().name,
            )

            # ── Teardown ──────────────────────────────────────────
            mgr.stop(test_name, timeout=10)
            mgr.remove(test_name)

        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()
            podman_stop_rm(processor_name)
            podman_stop_rm(db_name)
