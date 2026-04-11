"""Wrapper for the rclone CLI.

Handles dynamic configuration generation, securely decrypting remote credentials
and executing the rclone subprocess with bandwidth limits and checksums.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from silvasonic.core.crypto import decrypt_value
from silvasonic.core.schemas.cloud_sync import validate_rclone_config
from silvasonic.core.schemas.system_config import CloudSyncSettings

log = structlog.get_logger()


@dataclass
class RcloneResult:
    """Result of an upload attempt."""

    success: bool
    bytes_transferred: int
    error_message: str | None
    duration_s: float
    is_connection_error: bool


class RcloneClient:
    """Client for executing rclone commands."""

    def __init__(self, cloud_sync_settings: CloudSyncSettings, encryption_key: bytes) -> None:
        """Initialize the client with validated settings and key."""
        self.settings = cloud_sync_settings
        self.encryption_key = encryption_key

        # Pre-validate and decrypt config so we fail fast before uploading
        dt_config = self._decrypt_config(self.settings.remote_config)
        validate_rclone_config(str(self.settings.remote_type), dt_config)
        self.decrypted_config = dt_config

    def _decrypt_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Decrypt any enc: prefixed values in the remote config."""
        decrypted = {}
        for key, value in config.items():
            if isinstance(value, str) and value.startswith("enc:"):
                decrypted[key] = decrypt_value(value, self.encryption_key)
            else:
                decrypted[key] = value
        return decrypted

    async def _obscure_value(self, value: str) -> str:
        """Use rclone to obscure sensitive strings like passwords."""
        proc = await asyncio.create_subprocess_exec(
            "rclone",
            "obscure",
            value,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8").strip()

    async def _generate_rclone_conf(self) -> Path:
        """Generate a temporary rclone config file.

        Note: The returned Path must be unlinked by the caller!
        """
        import configparser

        parser = configparser.ConfigParser()
        parser["myremote"] = {"type": str(self.settings.remote_type)}
        for key, value in self.decrypted_config.items():
            if "pass" in key.lower():
                parser["myremote"][key] = await self._obscure_value(str(value))
            else:
                parser["myremote"][key] = str(value)

        # Write to secure temporary file
        fd, config_path = tempfile.mkstemp(prefix="silvasonic_rclone_", suffix=".conf")
        with open(fd, "w", encoding="utf-8") as f:
            parser.write(f)

        return Path(config_path)

    async def upload_file(self, local_path: Path, remote_path: str) -> RcloneResult:
        """Upload a local file to the configured remote.

        Args:
            local_path: Absolute path to the local file to upload.
            remote_path: Target path on the remote, e.g., 'silvasonic/station/.../file.flac'.

        Returns:
            RcloneResult with the transfer outcome.
        """
        start_time = time.monotonic()
        config_file = await self._generate_rclone_conf()

        try:
            # We copy a single file: `rclone copyto local myremote:remote_path`
            target = f"myremote:{remote_path}"

            cmd = [
                "rclone",
                "copyto",
                str(local_path),
                target,
                "--config",
                str(config_file),
                "--checksum",
                "--stats-one-line",
            ]

            if self.settings.bandwidth_limit:
                cmd.extend(["--bwlimit", self.settings.bandwidth_limit])

            log.debug("rclone.upload.start", source=local_path.name, target=remote_path)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr = await proc.communicate()
            duration = time.monotonic() - start_time

            err_output = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                is_conn_error = any(
                    x in err_output.lower()
                    for x in ["timeout", "dial tcp", "connection refused", "network is unreachable"]
                )

                log.error(
                    "rclone.upload.failed",
                    source=local_path.name,
                    code=proc.returncode,
                    is_conn_error=is_conn_error,
                    error=err_output[:500],
                )
                return RcloneResult(
                    success=False,
                    bytes_transferred=0,
                    error_message=err_output.strip() or f"rclone exit {proc.returncode}",
                    duration_s=duration,
                    is_connection_error=is_conn_error,
                )

            # Success
            size = local_path.stat().st_size
            log.debug("rclone.upload.success", source=local_path.name, size=size, duration=duration)
            return RcloneResult(
                success=True,
                bytes_transferred=size,
                error_message=None,
                duration_s=duration,
                is_connection_error=False,
            )

        finally:
            config_file.unlink(missing_ok=True)
