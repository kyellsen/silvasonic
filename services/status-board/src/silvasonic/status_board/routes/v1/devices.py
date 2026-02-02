from typing import Any

from fastapi import APIRouter, HTTPException, Query
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.models.system import Device
from silvasonic.core.database.session import AsyncSessionLocal
from silvasonic.status_board.schemas import (
    DeviceResponse,
    DeviceUpdate,
)
from sqlalchemy import select

router = APIRouter(tags=["Devices"])


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(
    enrollment_status: str | None = Query(None, pattern="^(pending|enrolled|ignored)$"),
    status: str | None = None,
) -> Any:
    """List all devices with optional filtering."""
    async with AsyncSessionLocal() as session:
        stmt = select(Device)
        if enrollment_status:
            stmt = stmt.where(Device.enrollment_status == enrollment_status)
        if status:
            stmt = stmt.where(Device.status == status)

        # Sort by Name
        stmt = stmt.order_by(Device.name)

        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/devices/{serial_number}", response_model=DeviceResponse)
async def get_device(serial_number: str) -> Any:
    """Get single device details."""
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.serial_number == serial_number)
        result = await session.execute(stmt)
        device = result.scalar_one_or_none()

        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return device


@router.patch("/devices/{serial_number}", response_model=DeviceResponse)
async def update_device(serial_number: str, payload: DeviceUpdate) -> Any:
    """Update device state (Enroll, Ignore, etc)."""
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.serial_number == serial_number)
        result = await session.execute(stmt)
        device = result.scalar_one_or_none()

        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        # Apply Updates
        if payload.enrollment_status:
            device.enrollment_status = payload.enrollment_status

        if payload.profile_slug is not None:
            # Verify Profile Exists if not clearing
            if payload.profile_slug:
                p_check = await session.get(MicrophoneProfile, payload.profile_slug)
                if not p_check:
                    raise HTTPException(status_code=400, detail="Profile slug not found")
            device.profile_slug = payload.profile_slug

        if payload.logical_name:
            # Skipping rename logic for now as name is PK
            pass

        if payload.enabled is not None:
            device.enabled = payload.enabled

        await session.commit()
        await session.refresh(device)
        return device
