"""Startup seeders for Controller — idempotent DB bootstrapping (ADR-0023).

Three seeders run on every Controller startup in sequence:

1. **ConfigSeeder** — Populates ``system_config`` with factory defaults.
2. **ProfileBootstrapper** — Seeds microphone profiles from bundled YAML files.
3. **AuthSeeder** — Creates default admin user with bcrypt-hashed password.

All seeders use ``INSERT … ON CONFLICT DO NOTHING`` semantics: existing
user-modified values are **never** overwritten.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import bcrypt
import structlog
import yaml
from pydantic import ValidationError
from silvasonic.core.config_schemas import (
    AuthDefaults,
    BirdnetSettings,
    ProcessorSettings,
    SystemSettings,
    UploaderSettings,
)
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import SystemConfig, User
from silvasonic.core.schemas.devices import MicrophoneProfile as MicProfileSchema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _find_service_root(start: Path = Path(__file__).resolve()) -> Path:
    """Walk up until ``pyproject.toml`` is found (service root)."""
    for parent in start.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return start.parent  # Fallback: same directory


@cache
def _get_config_dir() -> Path:
    """Return config dir, resolved lazily on first call."""
    return _find_service_root() / "config"


@cache
def _get_defaults_yml() -> Path:
    """Return defaults.yml path, resolved lazily on first call."""
    return _get_config_dir() / "defaults.yml"


@cache
def _get_profiles_dir() -> Path:
    """Return profiles dir, resolved lazily on first call."""
    return _get_config_dir() / "profiles"


# ---------------------------------------------------------------------------
# ConfigSeeder
# ---------------------------------------------------------------------------
class ConfigSeeder:
    """Seed ``system_config`` with factory defaults (ADR-0023 §2.3).

    Each key is inserted only if it does **not** already exist.
    """

    def __init__(self, defaults_path: Path | None = None) -> None:
        """Initialize with path to defaults YAML file."""
        self._defaults_path = defaults_path

    async def seed(self, session: AsyncSession) -> None:
        """Load ``defaults.yml`` and insert missing keys into ``system_config``."""
        defaults_path = self._defaults_path or _get_defaults_yml()
        if not defaults_path.exists():
            log.warning("seeder.config.no_defaults_file", path=str(defaults_path))
            return

        raw = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            log.error("seeder.config.invalid_yaml", path=str(defaults_path))
            return

        # Only seed keys that have a Pydantic schema mapping
        schema_map: dict[str, type] = {
            "system": SystemSettings,
            "birdnet": BirdnetSettings,
            "processor": ProcessorSettings,
            "uploader": UploaderSettings,
        }

        for key, value in raw.items():
            if key == "auth":
                continue  # Handled by AuthSeeder

            # Validate against Pydantic schema if one exists
            schema = schema_map.get(key)
            if schema:
                try:
                    validated = schema(**value)
                    value = validated.model_dump()
                except ValidationError as exc:
                    log.error(
                        "seeder.config.validation_failed",
                        key=key,
                        errors=exc.error_count(),
                    )
                    continue

            # INSERT ON CONFLICT DO NOTHING
            existing = await session.get(SystemConfig, key)
            if existing is None:
                session.add(SystemConfig(key=key, value=value))
                log.info("seeder.config.inserted", key=key)
            else:
                log.debug("seeder.config.skipped", key=key)


# ---------------------------------------------------------------------------
# ProfileBootstrapper
# ---------------------------------------------------------------------------
class ProfileBootstrapper:
    """Seed ``microphone_profiles`` from YAML files (ADR-0016).

    Reads all ``*.yml`` files from the ``profiles/`` directory,
    validates each against the ``MicrophoneProfile`` Pydantic schema,
    and inserts into the DB if the ``slug`` does not already exist.
    """

    def __init__(self, profiles_dir: Path | None = None) -> None:
        """Initialize with path to profiles directory."""
        self._profiles_dir = profiles_dir

    async def seed(self, session: AsyncSession) -> None:
        """Load YAML profiles and insert missing ones into ``microphone_profiles``."""
        profiles_dir = self._profiles_dir or _get_profiles_dir()
        if not profiles_dir.is_dir():
            log.warning(
                "seeder.profiles.no_directory",
                path=str(profiles_dir),
            )
            return

        yml_files = sorted(profiles_dir.glob("*.yml"))
        if not yml_files:
            log.info("seeder.profiles.no_files")
            return

        for yml_path in yml_files:
            if yml_path.name == ".gitkeep":
                continue

            try:
                raw = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                log.error("seeder.profiles.yaml_parse_error", file=yml_path.name)
                continue

            if not isinstance(raw, dict) or "slug" not in raw:
                log.error("seeder.profiles.missing_slug", file=yml_path.name)
                continue

            # Validate against Pydantic schema
            try:
                validated = MicProfileSchema(**raw)
            except ValidationError as exc:
                log.error(
                    "seeder.profiles.validation_failed",
                    file=yml_path.name,
                    errors=exc.error_count(),
                )
                continue

            slug = validated.slug

            # Check if already exists → skip (Controller README §Seeding)
            existing = await session.get(MicProfileDB, slug)
            if existing is not None:
                log.debug("seeder.profiles.skipped", slug=slug)
                continue

            # Build config JSONB from validated sections
            config_data: dict[str, Any] = {
                "audio": validated.audio.model_dump(),
                "processing": validated.processing.model_dump(),
                "stream": validated.stream.model_dump(),
            }

            db_profile = MicProfileDB(
                slug=slug,
                name=validated.name,
                description=validated.description,
                match_pattern=None,  # Legacy field, match is in config.audio.match
                config=config_data,
                is_system=True,
            )
            session.add(db_profile)
            log.info("seeder.profiles.inserted", slug=slug, file=yml_path.name)


# ---------------------------------------------------------------------------
# AuthSeeder
# ---------------------------------------------------------------------------
class AuthSeeder:
    """Seed default admin user (ADR-0023 §2.4).

    Creates a default admin with bcrypt-hashed password.
    Skips if a user with the same username already exists.
    """

    def __init__(self, defaults_path: Path | None = None) -> None:
        """Initialize with path to defaults YAML file."""
        self._defaults_path = defaults_path

    async def seed(self, session: AsyncSession) -> None:
        """Create default admin user if not exists."""
        defaults_path = self._defaults_path or _get_defaults_yml()
        if not defaults_path.exists():
            log.warning("seeder.auth.no_defaults_file", path=str(defaults_path))
            return

        raw = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "auth" not in raw:
            log.debug("seeder.auth.no_auth_section")
            return

        try:
            auth = AuthDefaults(**raw["auth"])
        except ValidationError as exc:
            log.error("seeder.auth.validation_failed", errors=exc.error_count())
            return

        username = auth.default_username
        password = auth.default_password

        # Check if user already exists
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()

        if existing is not None:
            log.debug("seeder.auth.skipped", username=username)
            return

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

        session.add(
            User(
                username=username,
                password_hash=password_hash,
            )
        )
        log.info("seeder.auth.created", username=username)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def run_all_seeders(session: AsyncSession) -> None:
    """Run all seeders in order: config → profiles → auth.

    All operations are idempotent. Existing user-modified values
    are never overwritten.
    """
    log.info("seeder.start")

    await ConfigSeeder().seed(session)
    await ProfileBootstrapper().seed(session)
    await AuthSeeder().seed(session)

    await session.commit()
    log.info("seeder.complete")
