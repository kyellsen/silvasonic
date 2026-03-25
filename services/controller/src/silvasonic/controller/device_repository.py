"""Device persistence — insert-or-update operations for the ``devices`` table.

Extracted from ``device_scanner.py`` to separate hardware detection (sysfs/ALSA)
from database persistence (SRP).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.core.database.models.system import Device
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


async def upsert_device(
    device_info: DeviceInfo,
    session: AsyncSession,
    *,
    profile_slug: str | None = None,
    enrollment_status: str = "pending",
) -> Device:
    """Insert or update a device in the ``devices`` table.

    - **New device:** inserts with ``status=online``, given enrollment status.
    - **Known device:** updates ``status=online``, ``last_seen=now()``.
    - If ``profile_slug`` is provided, sets it on the device.

    Args:
        device_info: Scanned device information.
        session: Active async DB session (caller manages commit).
        profile_slug: Optional profile to assign.
        enrollment_status: Initial enrollment status (default: ``pending``).

    Returns:
        The Device row (new or updated).
    """
    device_id = device_info.stable_device_id

    result = await session.execute(select(Device).where(Device.name == device_id))
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.status = "online"
        existing.last_seen = datetime.now(UTC)
        if profile_slug and not existing.profile_slug:  # pragma: no cover — integration-tested
            existing.profile_slug = profile_slug
            existing.enrollment_status = enrollment_status
        log.debug("device_scanner.device_updated", device_id=device_id)
        return existing

    device = Device(
        name=device_id,
        serial_number=device_info.usb_serial or device_id,
        model=device_info.alsa_name,
        status="online",
        enrollment_status=enrollment_status,
        last_seen=datetime.now(UTC),
        enabled=True,
        profile_slug=profile_slug,
        config={
            "alsa_card_index": device_info.alsa_card_index,
            "alsa_device": device_info.alsa_device,
            "alsa_name": device_info.alsa_name,
            "usb_vendor_id": device_info.usb_vendor_id,
            "usb_product_id": device_info.usb_product_id,
            "usb_serial": device_info.usb_serial,
            "usb_bus_path": device_info.usb_bus_path,
        },
    )
    session.add(device)
    log.info("device_scanner.device_created", device_id=device_id)
    return device
