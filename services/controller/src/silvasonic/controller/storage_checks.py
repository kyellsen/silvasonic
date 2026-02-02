"""Storage Policy Enforcment Checks.

This module inspects the underlying filesystem of key directories to ensure
compliance with the hardware standards (Mandatory NVMe, Prohibited SD Card).
"""

import os
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Common SD Card identifiers in Linux /sys
SD_CARD_IDENTIFIERS = ["mmcblk", "sd_card"]


def _get_device_name_for_path(path: Path) -> str | None:
    """Resolve the block device name for a given path."""
    try:
        # 1. Get Device ID from stat
        if not path.exists():
            return None

        st = path.stat()
        major = os.major(st.st_dev)
        minor = os.minor(st.st_dev)

        # 2. Resolve via sysfs
        sys_path = Path(f"/sys/dev/block/{major}:{minor}")
        if sys_path.exists():
            real_path = sys_path.resolve()
            # real_path usually looks like /sys/devices/pci.../nvme0n1/nvme0n1p1 or mmcblk0p1
            return real_path.name

        return None
    except Exception as e:
        logger.warning("failed_to_resolve_device_name", path=str(path), error=str(e))
        return None


def check_storage_policy() -> None:
    """Verify that the Workspace is running on compliant storage (NVMe).

    Logs a warning if SD Card usage is detected.
    """
    # 1. Determine Workspace Path
    # We inspect the log dir as a proxy for the workspace mount
    log_dir = os.getenv("LOG_DIR", "/var/log/silvasonic")
    target_path = Path(log_dir)

    if not target_path.exists():
        # Fallback to current working directory or /app
        target_path = Path.cwd()

    logger.info("running_storage_policy_check", target_path=str(target_path))

    device_name = _get_device_name_for_path(target_path)

    if not device_name:
        logger.warning("storage_check_inconclusive", reason="device_not_resolved")
        return

    # 2. Check for Policy Violations
    is_sd_card = any(x in device_name for x in SD_CARD_IDENTIFIERS)

    if is_sd_card:
        logger.warning(
            "STORAGE_POLICY_VIOLATION",
            device=device_name,
            path=str(target_path),
            msg="System is running on SD Card (mmcblk). This is PROHIBITED for production.",
        )
        logger.warning(
            "PERFORMANCE_WARNING",
            msg="SD Cards cause high latency and wear-out. Please migrate workspace to NVMe.",
        )
    else:
        logger.info(
            "storage_policy_compliant",
            device=device_name,
            msg="Storage backend appears compliant (Non-SD).",
        )
