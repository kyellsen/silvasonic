"""Microphone persistence — insert-or-update operations for the ``microphones`` table.

Extracted from ``device_scanner.py`` to separate hardware detection (sysfs/ALSA)
from database persistence (SRP).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from silvasonic.controller.device_scanner import DeviceInfo
from silvasonic.core.database.models.system import Microphone
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


def _hardware_facts(device_info: DeviceInfo) -> dict[str, Any]:
    """Facts read from the USB/ALSA device, stored in ``microphones.hardware``."""
    return {
        "alsa_card_index": device_info.alsa_card_index,
        "alsa_device": device_info.alsa_device,
        "alsa_name": device_info.alsa_name,
        "usb_vendor_id": device_info.usb_vendor_id,
        "usb_product_id": device_info.usb_product_id,
        "usb_serial": device_info.usb_serial,
        "usb_bus_path": device_info.usb_bus_path,
    }


async def upsert_microphone(
    device_info: DeviceInfo,
    session: AsyncSession,
    *,
    profile_slug: str | None = None,
    enrollment_state: str = "pending",
) -> Microphone:
    """Insert or update a microphone in the ``microphones`` table.

    - **New microphone:** inserts with ``connection_state=connected``, the
      given enrollment state, ``first_seen_at=last_seen_at=now()`` and
      ``name`` set to the model.
    - **Known microphone:** updates ``connection_state=connected``,
      ``last_seen_at=now()``.
    - If ``profile_slug`` is provided, sets it on the microphone.

    The microphone is found by its ``hardware_id`` (the Stable Device ID).

    Args:
        device_info: Scanned device information.
        session: Active async DB session (caller manages commit).
        profile_slug: Optional profile to assign.
        enrollment_state: Initial enrollment state (default: ``pending``).

    Returns:
        The Microphone row (new or updated).
    """
    hardware_id = device_info.stable_device_id

    result = await session.execute(select(Microphone).where(Microphone.hardware_id == hardware_id))
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.connection_state = "connected"
        existing.last_seen_at = datetime.now(UTC)
        existing.model = device_info.alsa_name

        # --- BUGFIX: Sync volatile hardware state ---
        # We create a new dict to ensure SQLAlchemy registers the JSONB mutation
        updated_hardware = dict(existing.hardware) if existing.hardware else {}
        updated_hardware.update(_hardware_facts(device_info))
        existing.hardware = updated_hardware
        # --------------------------------------------

        if profile_slug and not existing.profile_slug:  # pragma: no cover — integration-tested
            existing.profile_slug = profile_slug
            existing.enrollment_state = enrollment_state
        log.debug("device_scanner.microphone_updated", hardware_id=hardware_id)
        return existing

    now = datetime.now(UTC)
    microphone = Microphone(
        hardware_id=hardware_id,
        name=device_info.alsa_name,
        serial_number=device_info.usb_serial or hardware_id,
        model=device_info.alsa_name,
        connection_state="connected",
        enrollment_state=enrollment_state,
        first_seen_at=now,
        last_seen_at=now,
        enabled=True,
        profile_slug=profile_slug,
        hardware=_hardware_facts(device_info),
    )
    session.add(microphone)
    log.info("device_scanner.microphone_created", hardware_id=hardware_id)
    return microphone
