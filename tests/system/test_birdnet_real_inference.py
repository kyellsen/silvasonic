"""System testing for BirdNET inference explicitly running real ai-edge-litert."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from silvasonic.birdnet.service import BirdNETService

# Default image name as built by podman-compose / just build
_BIRDNET_IMAGE = "localhost/silvasonic_birdnet:latest"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to audio fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "audio"


@pytest.fixture(scope="session")
def birdnet_model_dir() -> Path:
    """Ensure BirdNET models are available, extracting from container image if needed.

    On CI the models only exist inside the previously built container image.
    This fixture copies them to a host-local directory via ``podman cp`` so
    that the pytest process can access them directly.
    """
    model_dir = Path(
        os.environ.get("SILVASONIC_BIRDNET_MODEL_DIR", "/tmp/birdnet_models"),
    )
    sentinel = model_dir / "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite"

    if sentinel.exists():
        return model_dir

    # Models missing on host — extract from the built container image.
    model_dir.mkdir(parents=True, exist_ok=True)
    image = os.environ.get("SILVASONIC_BIRDNET_IMAGE", _BIRDNET_IMAGE)
    container = f"tmp_model_extract_{os.getpid()}"

    try:
        # Clean up any leftover container from a previous aborted run
        subprocess.run(
            ["podman", "rm", "-f", "--ignore", container],
            capture_output=True,
        )
        subprocess.run(
            ["podman", "create", "--name", container, image],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["podman", "cp", f"{container}:/app/models/.", str(model_dir)],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.skip(
            f"Cannot extract BirdNET models from image '{image}': {exc}. "
            "Run 'just build birdnet' first.",
        )
    finally:
        subprocess.run(
            ["podman", "rm", "-f", container],
            capture_output=True,
        )

    if not sentinel.exists():
        pytest.skip(f"Model extraction succeeded but {sentinel} is missing.")

    return model_dir


@pytest.mark.system
@pytest.mark.asyncio
async def test_native_tflite_inference(
    fixtures_dir: Path,
    birdnet_model_dir: Path,
    tmp_path: Path,
) -> None:
    """Test actual TFLite inference using the real models against an explicit fixture.

    Validates that the ai-edge-litert bindings work correctly with our exact numpy slicing
    and boolean mask implementations, independently of the DB.
    """
    # 1. Provide temporary env for the service config (skipping DB)
    with patch.dict(
        "os.environ",
        {
            "SILVASONIC_INSTANCE_ID": "sys-w",
            "SILVASONIC_WORKSPACE_DIR": str(tmp_path),
        },
    ):
        worker = BirdNETService()

    from silvasonic.core.schemas.system_config import BirdnetSettings, SystemSettings

    worker.birdnet_config = BirdnetSettings(
        confidence_threshold=0.65,
        sensitivity=1.0,
        overlap=0.0,
        threads=1,
        processing_order="oldest_first",
    )
    # Hamburg defaults for testing location filtering
    worker.system_config = SystemSettings(latitude=53.55, longitude=9.99)

    # 2. Use models provided by the birdnet_model_dir fixture
    model_dir = birdnet_model_dir
    model_path = model_dir / "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite"
    assert model_path.exists(), "TFLite Model missing."
    meta_model_path = model_dir / "BirdNET_GLOBAL_6K_V2.4_MData_Model_V2_FP16.tflite"
    labels_file = model_dir / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"

    with open(labels_file) as f:
        labels = [line.strip() for line in f.readlines()]

    # We must explicitly import Interpreter here to test it natively
    from ai_edge_litert.interpreter import Interpreter  # type: ignore

    interpreter = Interpreter(model_path=str(model_path), num_threads=1)
    interpreter.allocate_tensors()

    # Precompute mask
    with patch("silvasonic.birdnet.service.META_MODEL_PATH", meta_model_path):
        allowed_mask, loc_active = worker._get_allowed_species_mask(labels)

    assert loc_active is True

    # Create a fake Recording DB representation
    from datetime import UTC, datetime

    from silvasonic.core.database.models.recordings import Recording

    # Only ID is strictly used inside _process_recording
    recording = Recording(id=999, time=datetime(2024, 1, 1, tzinfo=UTC))

    # Test Fixture 1: European Robin
    robin_path = fixtures_dir / "XC521936 - European Robin - Erithacus rubecula.wav"
    assert robin_path.exists(), f"Fixture missing: {robin_path}"

    dets = await worker._process_recording(
        recording=recording,
        audio_path=robin_path,
        interpreter=interpreter,
        labels=labels,
        allowed_mask=allowed_mask,
        loc_filter_active=loc_active,
    )

    assert len(dets) > 0, "No detections found for Robin fixture"

    # Verify Robin is in top detections
    found_robin = any("Erithacus rubecula" in d.label for d in dets)
    assert found_robin is True, "Failed to accurately detect Erithacus rubecula"

    # Test Fixture 2: Common Blackbird
    bbird_path = fixtures_dir / "XC589788 - Common Blackbird - Turdus merula.wav"
    assert bbird_path.exists(), f"Fixture missing: {bbird_path}"

    dets = await worker._process_recording(
        recording=recording,
        audio_path=bbird_path,
        interpreter=interpreter,
        labels=labels,
        allowed_mask=allowed_mask,
        loc_filter_active=loc_active,
    )

    assert len(dets) > 0, "No detections found for Blackbird fixture"
    found_bb = any("Turdus merula" in d.label for d in dets)
    assert found_bb is True, "Failed to accurately detect Turdus merula"
