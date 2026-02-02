from pathlib import Path

import structlog
import yaml
from silvasonic.core.database.models.profiles import MicrophoneProfile
from silvasonic.core.database.session import AsyncSessionLocal
from sqlalchemy.dialects.postgresql import insert

logger = structlog.get_logger()


class ProfileBootstrapper:
    """Syncs YAML profiles from disk to the database on startup."""

    def __init__(self, profiles_dir: str = "/etc/silvasonic/profiles") -> None:
        """Initialize with path to profiles directory."""
        self.profiles_dir = Path(profiles_dir)

    async def sync(self) -> None:
        """Read all YAML profiles and upsert them into the DB."""
        if not self.profiles_dir.exists():
            logger.warning("profiles_directory_not_found", path=str(self.profiles_dir))
            # Create it just in case? Or just return.
            return

        profiles_to_sync = []

        # 1. Read Files
        for p_file in self.profiles_dir.glob("*.yml"):
            try:
                with open(p_file) as f:
                    data = yaml.safe_load(f)

                if not data or "slug" not in data:
                    logger.warning("invalid_profile_skipped", file=p_file.name)
                    continue

                profiles_to_sync.append(data)

            except Exception as e:
                logger.error("failed_to_read_profile", file=p_file.name, error=str(e))

        if not profiles_to_sync:
            logger.info("no_profiles_found_to_sync")
            return

        # 2. Upsert to DB
        async with AsyncSessionLocal() as session:
            try:
                for p_data in profiles_to_sync:
                    slug = p_data["slug"]
                    name = p_data.get("name", "Unknown")
                    match_pattern = p_data.get("audio", {}).get("match_pattern")

                    # Construct MicrophoneProfile object data
                    profile_dict = {
                        "slug": slug,
                        "name": name,
                        "description": p_data.get("description"),
                        "match_pattern": match_pattern,
                        "config": p_data,
                        "is_system": True,
                    }

                    # Upsert (PostgreSQL specific, but we utilize generic dialect if possible,
                    # but easiest is direct merge or insert on conflict)
                    stmt = insert(MicrophoneProfile).values(**profile_dict)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[MicrophoneProfile.slug],
                        set_={
                            "name": stmt.excluded.name,
                            "description": stmt.excluded.description,
                            "match_pattern": stmt.excluded.match_pattern,
                            "config": stmt.excluded.config,
                            "is_system": stmt.excluded.is_system,
                        },
                    )
                    await session.execute(stmt)

                await session.commit()
                logger.info("profiles_synced_to_db", count=len(profiles_to_sync))

            except Exception as e:
                logger.error("profile_sync_failed", error=str(e))
                await session.rollback()
