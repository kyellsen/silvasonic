"""Integration tests for RcloneClient against a real MinIO (S3) container.

Tests the full upload pipeline: generating rclone.conf locally, running the
rclone subprocess limit, and actually pushing the file to an S3 bucket.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import structlog
from minio import Minio
from silvasonic.core.crypto import encrypt_value, generate_key
from silvasonic.core.schemas.system_config import CloudSyncSettings
from silvasonic.processor.modules.rclone_client import RcloneClient
from testcontainers.minio import MinioContainer

log = structlog.get_logger()

# Minio bucket name for the test
BUCKET_NAME = "silvasonic-bucket"


@pytest.fixture(scope="session")
def minio_container() -> Generator[MinioContainer]:
    """Provide a real, ephemeral MinIO S3 bucket for the session."""
    with MinioContainer(image="docker.io/minio/minio:latest") as container:
        container.get_client().make_bucket(BUCKET_NAME)
        yield container


@pytest.fixture
def run_id(request: pytest.FixtureRequest) -> str:
    """Provide a unique ID per test to avoid path collisions."""
    import uuid

    return f"run_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rclone_client_uploads_to_minio(
    minio_container: MinioContainer,
    tmp_path: Path,
    run_id: str,
) -> None:
    """Verify that RcloneClient successfully uploads a file to S3 via rclone.

    1. Creates a synthetic FLAC file.
    2. Builds CloudSyncSettings targeting the MinIO container.
    3. Encrypts credentials (simulating DB seeder).
    4. Invokes RcloneClient.upload_file().
    5. Downloads the file via Minio SDK and verifies its contents.
    """
    # 1. Prepare synthetic local file
    flac_content = b"fake-flac-audio-content-12345"
    test_file = tmp_path / "test_recording.flac"
    test_file.write_bytes(flac_content)

    remote_path = f"silvasonic/station-alpha/mic-01/2026-04-03/{run_id}.flac"

    # 2. Get MinIO connection details
    # testcontainers minio returns 'host:port' without scheme. Rclone needs http://
    endpoint = minio_container.get_config()["endpoint"]
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    access_key = minio_container.access_key
    secret_key = minio_container.secret_key

    # 3. Simulate Database State (Encrypted credentials)
    # The Controller's CloudSyncSeeder encrypts string values with the system AES key
    enc_key = generate_key().encode("utf-8")

    settings = CloudSyncSettings(
        enabled=True,
        remote_type="s3",
        remote_config={
            "access_key_id": encrypt_value(access_key, enc_key),
            "secret_access_key": encrypt_value(secret_key, enc_key),
            "endpoint": endpoint,
            "region": "us-east-1",
            "provider": "Minio",
            "env_auth": "false",
            "force_path_style": "true",
        },
        bandwidth_limit="10M",
    )

    # 4. Instantiate RcloneClient and execute the upload
    client = RcloneClient(settings, enc_key)

    # upload_file maps local absolute path to remote relative path inside the bucket
    # Note: RcloneClient automatically prepends 'myremote:'
    rclone_target = f"{BUCKET_NAME}/{remote_path}"

    result = await client.upload_file(test_file, rclone_target)

    # 5. Verify Rclone Result
    assert result.success is True, f"Upload failed: {result.error_message}"
    assert result.bytes_transferred == len(flac_content)
    assert result.is_connection_error is False

    # 6. Verify file exists in MinIO bucket identically
    minio_client: Minio = minio_container.get_client()

    # Download into memory to check
    response = minio_client.get_object(BUCKET_NAME, remote_path)
    downloaded_content = response.read()
    response.close()

    assert downloaded_content == flac_content, "Uploaded content differs from local file"
    log.info("test_rclone_client_uploads_to_minio.success", path=remote_path)
