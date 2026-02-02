from typing import Any

from fastapi import APIRouter, HTTPException
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.session import AsyncSessionLocal
from silvasonic.status_board.schemas import (
    ProfileCreate,
    ProfileResponse,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

router = APIRouter(tags=["Profiles"])


@router.get("/profiles", response_model=list[ProfileResponse])
async def list_profiles() -> Any:
    """List all microphone profiles."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MicrophoneProfile).order_by(
                MicrophoneProfile.is_system.desc(), MicrophoneProfile.name
            )
        )
        return result.scalars().all()


@router.post("/profiles", response_model=ProfileResponse)
async def create_profile(payload: ProfileCreate) -> Any:
    """Create a new custom profile."""
    async with AsyncSessionLocal() as session:
        # Check existence
        existing = await session.get(MicrophoneProfile, payload.slug)
        if existing:
            raise HTTPException(status_code=409, detail="Profile slug already exists")

        new_profile = MicrophoneProfile(
            slug=payload.slug,
            name=payload.name,
            config=payload.config,
            is_system=False,  # Explicitly False for API created
            match_pattern=payload.match_pattern,
        )
        session.add(new_profile)
        await session.commit()
        await session.refresh(new_profile)
        return new_profile


@router.delete("/profiles/{slug}")
async def delete_profile(slug: str) -> dict[str, str]:
    """Delete a profile (non-system only)."""
    async with AsyncSessionLocal() as session:
        profile = await session.get(MicrophoneProfile, slug)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        if profile.is_system:
            raise HTTPException(status_code=403, detail="Cannot delete system profile")

        try:
            await session.delete(profile)
            await session.commit()
        except IntegrityError as e:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete profile: It is in use by one or more devices.",
            ) from e

        return {"status": "deleted", "slug": slug}
