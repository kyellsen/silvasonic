"""Hardware-dependent recording tests — require real USB microphone.

Tests the full recording pipeline with real audio hardware:
- Device validation (ALSA query, sample rate acceptance)
- Live audio capture via FFmpegPipeline → WAV file verification
- Full lifecycle: Plug → Scan → DB → Container with /dev/snd → WAV output

These tests are **never** included in CI or ``just check-all``.
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

from .conftest import (
    PODMAN_SOCKET,
    PRIMARY_MIC,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
    TEST_RUN_ID,
    ensure_test_network,
    require_recorder_image,
)

pytestmark = [
    pytest.mark.system_hw,
]


# ---------------------------------------------------------------------------
# Hardware detection helpers
# ---------------------------------------------------------------------------


def _has_usb_audio_device() -> bool:
    """Check if any USB-Audio device is present in /proc/asound/cards."""
    try:
        text = Path("/proc/asound/cards").read_text()
        return "USB-Audio" in text
    except (FileNotFoundError, PermissionError):
        return False


_USB_PRESENT = _has_usb_audio_device()


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
        for line in result.stdout.splitlines():
            if card_marker in line:
                print(f"\n  ✅ {alsa_device} queryable: {line.strip()}")
                break

    def test_ffmpeg_accepts_device(self, primary_device: DeviceInfo) -> None:
        """FFmpeg can open the ALSA device for a brief capture."""
        alsa_device = primary_device.alsa_device
        sample_rate = PRIMARY_MIC.sample_rate

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
        print(f"\n  ✅ FFmpeg accepts {alsa_device} at {sample_rate} Hz")


# ---------------------------------------------------------------------------
# Test: Real Audio Capture (FFmpeg pipeline → WAV)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestRealAudioCapture:
    """Verify that FFmpegPipeline produces valid WAV files with real hardware.

    Uses a short segment duration (3s) to keep test runtime reasonable.
    The pipeline runs for ~8s to ensure at least one segment is promoted.
    """

    _SEGMENT_S = 3
    _CAPTURE_S = 8

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

    def test_pipeline_captures_audio(
        self,
        primary_device: DeviceInfo,
        tmp_path: Path,
    ) -> None:
        """FFmpegPipeline with real device produces at least 1 WAV file."""
        workspace = tmp_path / "capture_test"
        pipeline = self._make_pipeline(
            workspace,
            primary_device.alsa_device,
            PRIMARY_MIC.sample_rate,
        )

        self._run_pipeline(pipeline, self._CAPTURE_S)
        assert not pipeline.is_active, "Pipeline should be inactive after stop()"

        data_dir = workspace / "data" / "raw"
        wav_files = list(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, (
            f"Expected at least 1 WAV file in {data_dir}, "
            f"found {len(wav_files)}. "
            f"Buffer dir contents: {list((workspace / '.buffer' / 'raw').glob('*'))}"
        )
        print(f"\n  ✅ Captured {len(wav_files)} raw WAV file(s) in {data_dir}")

        proc_dir = workspace / "data" / "processed"
        proc_wavs = list(proc_dir.glob("*.wav"))
        assert len(proc_wavs) >= 1, (
            f"Expected at least 1 processed WAV in {proc_dir}, found {len(proc_wavs)}"
        )
        print(f"  ✅ Captured {len(proc_wavs)} processed WAV file(s) in {proc_dir}")

    def test_wav_is_valid(
        self,
        primary_device: DeviceInfo,
        tmp_path: Path,
    ) -> None:
        """Captured WAV file has valid metadata (use ffprobe)."""
        workspace = tmp_path / "wav_valid_test"
        pipeline = self._make_pipeline(
            workspace,
            primary_device.alsa_device,
            PRIMARY_MIC.sample_rate,
        )

        self._run_pipeline(pipeline, self._CAPTURE_S)

        data_dir = workspace / "data" / "raw"
        wav_files = list(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, "No WAV files captured"

        wav_path = wav_files[0]
        # Use ffprobe to validate WAV metadata
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=sample_rate,channels,codec_name",
                "-of",
                "csv=p=0",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, f"ffprobe failed: {result.stderr}"
        parts = result.stdout.strip().split(",")
        assert len(parts) >= 2, f"Unexpected ffprobe output: {result.stdout}"
        print(f"\n  ✅ Raw WAV valid: {wav_path.name} ({result.stdout.strip()})")

        # Verify processed WAV
        proc_dir = workspace / "data" / "processed"
        proc_wavs = list(proc_dir.glob("*.wav"))
        assert len(proc_wavs) >= 1, "No processed WAV files captured"

        proc_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "csv=p=0",
                str(proc_wavs[0]),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        proc_sr = proc_result.stdout.strip()
        assert proc_sr == str(PROCESSED_SAMPLE_RATE), (
            f"Processed WAV SR {proc_sr} != {PROCESSED_SAMPLE_RATE}"
        )
        print(f"  ✅ Processed WAV valid: {proc_wavs[0].name} ({proc_sr} Hz)")


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
        tmp_path: Path,
    ) -> None:
        """Full lifecycle: Plug → Scan → Match → DB → Container → WAV output.

        Steps:
        1. Use detected primary device (already scanned via fixture).
        2. Match against seeded profiles → auto-enroll.
        3. Evaluate desired state → Tier2ServiceSpec.
        4. Start container with REAL /dev/snd passthrough.
        5. Wait for recording (short segment duration).
        6. Stop container and verify WAV files in workspace.
        """
        require_recorder_image()
        ensure_test_network()

        session_factory = seeded_db

        # Step 2: Match profile
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(primary_device, session)

        if match_result.score < 100:
            pytest.skip(
                f"Primary mic ({primary_device.alsa_name}) did not match "
                f"profile '{PRIMARY_MIC.slug}' (score={match_result.score})"
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
            network=spec.network,
            environment={
                **spec.environment,
                "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
            },
            labels={
                **spec.labels,
                "io.silvasonic.test": "system_hw",
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

            # Step 6: Wait for container to record at least one segment
            wait_seconds = 20
            print(f"\n  ⏳ Waiting {wait_seconds}s for container to record audio...")
            time.sleep(wait_seconds)

            # Step 7: Stop container gracefully (promotes final segment)
            mgr.stop(test_name, timeout=10)

            # Step 8: Verify WAV files exist in the workspace
            data_dir = workspace / "data" / "raw"
            buffer_dir = workspace / ".buffer" / "raw"

            wav_in_data = list(data_dir.glob("*.wav")) if data_dir.exists() else []
            wav_in_buffer = list(buffer_dir.glob("*.wav")) if buffer_dir.exists() else []
            total_wavs = len(wav_in_data) + len(wav_in_buffer)

            if total_wavs < 1:
                try:
                    logs = subprocess.run(
                        ["podman", "logs", test_name], capture_output=True, text=True
                    )
                    print(
                        f"\n--- CONTAINER LOGS ({test_name}) ---\n"
                        f"{logs.stderr}\n{logs.stdout}\n"
                        "----------------------------------"
                    )
                except Exception as e:
                    print(f"Could not fetch podman logs: {e}")

            assert total_wavs >= 1, (
                f"No WAV files found in workspace {workspace}. "
                f"data/raw: {wav_in_data}, .buffer/raw: {wav_in_buffer}. "
                f"Check container logs with: podman logs {test_name}"
            )

            print(
                f"\n  ✅ Full lifecycle verified: "
                f"{len(wav_in_data)} promoted + "
                f"{len(wav_in_buffer)} buffered raw WAV file(s)"
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

    This is the comprehensive production-path confidence test for v0.4.0.
    Unlike ``TestFullHardwareLifecycle``, this test also includes:

    - A real Redis on ``silvasonic-net`` for heartbeat verification.
    - WAV header validation (sample rate, channels, format).
    - Redis heartbeat assertions (service, health, watchdog metadata).
    - Container health-endpoint check.
    """

    _WAIT_SECONDS = 18  # Enough for 2-3 segment promotions (3s segments)

    async def test_full_pipeline_with_heartbeat(
        self,
        primary_device: DeviceInfo,
        seeded_db: async_sessionmaker[AsyncSession],
        hw_redis: tuple[str, int],
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
        ensure_test_network()

        session_factory = seeded_db
        redis_host, redis_port = hw_redis

        # ── Step 1: Match profile ──────────────────────────────────
        matcher = ProfileMatcher()
        async with session_factory() as session:
            match_result = await matcher.match(primary_device, session)

        if match_result.score < 100:
            pytest.skip(
                f"Primary mic ({primary_device.alsa_name}) did not match "
                f"profile '{PRIMARY_MIC.slug}' (score={match_result.score})"
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
            network=spec.network,
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

            print(f"\n  ⏳ Recording for {self._WAIT_SECONDS}s...")
            time.sleep(self._WAIT_SECONDS)

            # ── Step 5: Assert WAV files exist ─────────────────────
            raw_data = workspace / "data" / "raw"
            proc_data = workspace / "data" / "processed"

            raw_wavs = list(raw_data.glob("*.wav")) if raw_data.exists() else []
            proc_wavs = list(proc_data.glob("*.wav")) if proc_data.exists() else []

            if not raw_wavs and not proc_wavs:
                # Dump container logs for debugging
                try:
                    logs = subprocess.run(
                        ["podman", "logs", test_name],
                        capture_output=True,
                        text=True,
                    )
                    print(
                        f"\n--- CONTAINER LOGS ({test_name}) ---\n"
                        f"{logs.stderr}\n{logs.stdout}\n"
                        "----------------------------------"
                    )
                except Exception as e:
                    print(f"Could not fetch container logs: {e}")

            assert len(raw_wavs) >= 1, (
                f"No raw WAV files in {raw_data}. Check container logs: podman logs {test_name}"
            )
            assert len(proc_wavs) >= 1, (
                f"No processed WAV files in {proc_data}. "
                f"Check container logs: podman logs {test_name}"
            )
            print(f"  ✅ WAV files: {len(raw_wavs)} raw, {len(proc_wavs)} processed")

            # ── Step 6: Validate WAV headers (via ffprobe) ────────
            def _ffprobe_wav(path: Path) -> tuple[int, int, str]:
                """Return (sample_rate, channels, codec) via ffprobe."""
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

            raw_sr, raw_ch, raw_codec = _ffprobe_wav(raw_wavs[0])
            assert raw_ch >= 1
            assert raw_sr == PRIMARY_MIC.sample_rate, (
                f"Raw WAV sample rate {raw_sr} != expected {PRIMARY_MIC.sample_rate}"
            )
            print(f"  ✅ Raw WAV: {raw_sr} Hz, {raw_ch} ch, {raw_codec}")

            proc_sr, proc_ch, proc_codec = _ffprobe_wav(proc_wavs[0])
            assert proc_ch >= 1
            assert proc_sr == PROCESSED_SAMPLE_RATE, (
                f"Processed WAV sample rate {proc_sr} != expected {PROCESSED_SAMPLE_RATE}"
            )
            print(f"  ✅ Processed WAV: {proc_sr} Hz, {proc_ch} ch, {proc_codec}")

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
            # Key format: silvasonic:status:<instance_id> (instance_id = device ID, NOT "recorder")
            # We must check the JSON payload's "service" field to find the recorder heartbeat.
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

            # Phase 5: Watchdog metadata
            assert "watchdog_restarts" in payload["meta"]["recording"], (
                "Watchdog metadata missing from heartbeat"
            )
            assert payload["meta"]["recording"]["watchdog_restarts"] == 0

            print(
                "  ✅ Redis heartbeat verified: "
                f"service={payload['service']}, "
                f"health={payload['health']['status']}, "
                f"watchdog_restarts={payload['meta']['recording']['watchdog_restarts']}"
            )
            redis_client.close()

            # ── Step 8: Health endpoint ────────────────────────────
            # The container exposes port 9500 — check via podman exec
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
            print("  ✅ Health endpoint: 200 OK")

            # ── Teardown ───────────────────────────────────────────
            mgr.stop(test_name, timeout=10)
            mgr.remove(test_name)

            print(
                "\n  🎉 Full Pipeline E2E PASSED: "
                "USB → DB → Podman → FFmpeg → WAV ✓ → "
                "Redis Heartbeat ✓ → Health ✓"
            )
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()
