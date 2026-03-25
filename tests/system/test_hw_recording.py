"""Hardware-dependent recording tests — require real USB microphone.

Tests the full recording pipeline with real audio hardware:
- Device validation (ALSA query, sample rate acceptance)
- Live audio capture via AudioPipeline → WAV file verification
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
import time
from pathlib import Path

import numpy as np
import pytest
import sounddevice as sd
import soundfile as sf
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
from silvasonic.recorder.pipeline import AudioPipeline, PipelineConfig
from silvasonic.recorder.workspace import ensure_workspace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import (
    PODMAN_SOCKET,
    PRIMARY_MIC,
    RECORDER_IMAGE,
    SOCKET_AVAILABLE,
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
    queryable by sounddevice and that the profile's sample rate is
    accepted — critical after the PortAudioError bug with UltraMic.
    """

    def test_alsa_device_queryable(self, primary_device: DeviceInfo) -> None:
        """Primary mic's ALSA device can be queried via sounddevice.

        Verifies that ``sd.query_devices(hw:X,0)`` returns valid info
        with at least 1 input channel.
        """
        alsa_device = primary_device.alsa_device
        info = sd.query_devices(alsa_device)
        assert isinstance(info, dict), f"query_devices({alsa_device}) did not return dict"
        assert info["max_input_channels"] >= 1, f"{alsa_device} has no input channels: {info}"
        print(
            f"\n  ✅ {alsa_device} queryable: "
            f"name={info['name']}, "
            f"default_sr={info['default_samplerate']}, "
            f"inputs={info['max_input_channels']}"
        )

    def test_profile_sample_rate_accepted(self, primary_device: DeviceInfo) -> None:
        """Profile's configured sample rate is accepted by the real device.

        Uses ``sd.check_input_settings()`` to validate before opening
        a stream.  This catches the PortAudioError that occurred with
        UltraMic 384 EVO when using an unsupported sample rate.
        """
        alsa_device = primary_device.alsa_device
        sample_rate = PRIMARY_MIC.sample_rate

        try:
            sd.check_input_settings(
                device=alsa_device,
                samplerate=sample_rate,
                channels=1,
            )
        except sd.PortAudioError as exc:
            pytest.fail(f"Profile sample rate {sample_rate} Hz rejected by {alsa_device}: {exc}")

        print(f"\n  ✅ {alsa_device} accepts {sample_rate} Hz (profile: {PRIMARY_MIC.slug})")


# ---------------------------------------------------------------------------
# Test: Real Audio Capture (pipeline → WAV)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _USB_PRESENT, reason="No USB-Audio device connected")
class TestRealAudioCapture:
    """Verify that AudioPipeline produces valid WAV files with real hardware.

    Uses a short segment duration (3s) to keep test runtime reasonable.
    The pipeline runs for ~5s to ensure at least one segment is promoted.
    """

    # Short config for testing
    _SEGMENT_S = 3
    _CAPTURE_S = 5  # Must be > _SEGMENT_S to trigger promotion

    def _make_pipeline(
        self,
        workspace: Path,
        device: str,
        sample_rate: int,
    ) -> AudioPipeline:
        """Create a pipeline with test-friendly short segment duration."""
        ensure_workspace(workspace)
        cfg = PipelineConfig(
            sample_rate=sample_rate,
            channels=1,
            format="S16LE",
            chunk_size=4096,
            segment_duration_s=self._SEGMENT_S,
            gain_db=0.0,
        )
        return AudioPipeline(config=cfg, workspace=workspace, device=device)

    @staticmethod
    def _run_pipeline(pipeline: AudioPipeline, duration_s: float) -> None:
        """Start pipeline, drain queue for *duration_s*, then stop.

        Mirrors the ``RecorderService.run()`` drain loop (~20 Hz) so that
        the PortAudio callback queue is consumed continuously.  Without
        draining, the 64-slot queue fills in <1 s at 384 kHz and all
        subsequent audio data is silently dropped.
        """
        pipeline.start()
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            pipeline.drain_queue()
            time.sleep(0.05)  # ~20 Hz — matches RecorderService
        pipeline.stop()

    def test_pipeline_captures_audio(
        self,
        primary_device: DeviceInfo,
        tmp_path: Path,
    ) -> None:
        """AudioPipeline with real device produces at least 1 WAV file."""
        workspace = tmp_path / "capture_test"
        pipeline = self._make_pipeline(
            workspace,
            primary_device.alsa_device,
            PRIMARY_MIC.sample_rate,
        )

        self._run_pipeline(pipeline, self._CAPTURE_S)
        assert not pipeline.is_active, "Pipeline should be inactive after stop()"

        # Check for promoted WAV files
        data_dir = workspace / "data" / "raw"
        wav_files = list(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, (
            f"Expected at least 1 WAV file in {data_dir}, "
            f"found {len(wav_files)}. "
            f"Buffer dir contents: {list((workspace / '.buffer' / 'raw').glob('*'))}"
        )
        print(f"\n  ✅ Captured {len(wav_files)} WAV file(s) in {data_dir}")

    def test_wav_is_valid(
        self,
        primary_device: DeviceInfo,
        tmp_path: Path,
    ) -> None:
        """Captured WAV file is a valid audio file with correct parameters."""
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

        # Validate WAV with soundfile
        wav_path = wav_files[0]
        info = sf.info(str(wav_path))

        assert info.samplerate == PRIMARY_MIC.sample_rate, (
            f"WAV sample rate {info.samplerate} != profile {PRIMARY_MIC.sample_rate}"
        )
        assert info.channels == 1, f"Expected 1 channel, got {info.channels}"
        assert info.frames > 0, "WAV file has 0 frames"

        # Duration should be approximately segment_duration_s
        duration = info.frames / info.samplerate
        assert duration > 0.5, f"WAV too short: {duration:.2f}s"

        print(
            f"\n  ✅ WAV valid: {wav_path.name} "
            f"({info.samplerate} Hz, {info.channels}ch, "
            f"{info.frames} frames, {duration:.1f}s)"
        )

    def test_wav_contains_nonzero_data(
        self,
        primary_device: DeviceInfo,
        tmp_path: Path,
    ) -> None:
        """Captured WAV contains non-zero audio data (real microphone input)."""
        workspace = tmp_path / "nonzero_test"
        pipeline = self._make_pipeline(
            workspace,
            primary_device.alsa_device,
            PRIMARY_MIC.sample_rate,
        )

        self._run_pipeline(pipeline, self._CAPTURE_S)

        data_dir = workspace / "data" / "raw"
        wav_files = list(data_dir.glob("*.wav"))
        assert len(wav_files) >= 1, "No WAV files captured"

        data, sr = sf.read(str(wav_files[0]), dtype="int16")
        assert sr == PRIMARY_MIC.sample_rate

        # Real audio should not be all zeros
        nonzero_count = int(np.count_nonzero(data))
        total = len(data)
        assert nonzero_count > 0, (
            "WAV contains only silence (all zeros). Is the microphone actually capturing audio?"
        )

        pct = (nonzero_count / total) * 100
        print(
            f"\n  ✅ WAV non-zero: {nonzero_count}/{total} samples "
            f"({pct:.1f}%) — real audio confirmed"
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

    This is the critical test that was missing: it verifies the ENTIRE
    production lifecycle from USB device detection to actual audio
    recording inside a containerized Recorder with /dev/snd passthrough.
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
        from silvasonic.controller.device_scanner import upsert_device

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
        test_name = "silvasonic-recorder-system-test-hw-lifecycle"

        # Use tmp_path (real FS, not tmpfs) — never write into the repo tree
        workspace = tmp_path / "hw_lifecycle"
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o777)

        test_spec = Tier2ServiceSpec(
            image=RECORDER_IMAGE,
            name=test_name,
            network=spec.network,
            environment={
                **spec.environment,
                # Override segment duration for faster test
                "SILVASONIC_RECORDER_WORKSPACE": "/app/workspace",
            },
            labels={
                **spec.labels,
                "io.silvasonic.test": "system_hw",
            },
            mounts=[
                MountSpec(
                    source=str(workspace),
                    target="/app/workspace",
                    read_only=False,
                ),
            ],
            # CRITICAL: Pass real /dev/snd for actual audio capture
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
            mgr = ContainerManager(client)
            info = mgr.start(test_spec)
            assert info is not None, "Container start failed"
            assert info.get("name") == test_name

            # Step 6: Wait for container to record at least one segment
            # The default segment is 10-15s; we wait enough time
            wait_seconds = 20
            print(f"\n  ⏳ Waiting {wait_seconds}s for container to record audio...")
            time.sleep(wait_seconds)

            # Step 7: Stop container gracefully (promotes final segment)
            mgr.stop(test_name, timeout=10)

            # Step 8: Verify WAV files exist in the workspace
            data_dir = workspace / "data" / "raw"
            buffer_dir = workspace / ".buffer" / "raw"

            # Check both data and buffer directories
            wav_in_data = list(data_dir.glob("*.wav")) if data_dir.exists() else []
            wav_in_buffer = list(buffer_dir.glob("*.wav")) if buffer_dir.exists() else []
            total_wavs = len(wav_in_data) + len(wav_in_buffer)

            if total_wavs < 1:
                # Capture logs to help debug
                try:
                    import subprocess

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

            # Validate the WAV file(s)
            for wav_path in wav_in_data:
                wav_info = sf.info(str(wav_path))
                assert wav_info.frames > 0, f"WAV {wav_path.name} has 0 frames"
                duration = wav_info.frames / wav_info.samplerate
                print(
                    f"  ✅ {wav_path.name}: "
                    f"{wav_info.samplerate} Hz, "
                    f"{wav_info.channels}ch, "
                    f"{duration:.1f}s"
                )

            print(
                f"\n  ✅ Full lifecycle verified: "
                f"{len(wav_in_data)} promoted + "
                f"{len(wav_in_buffer)} buffered WAV file(s)"
            )

            # Cleanup
            mgr.remove(test_name)
        finally:
            with contextlib.suppress(Exception):
                client.containers.get(test_name).remove(force=True)
            client.close()
