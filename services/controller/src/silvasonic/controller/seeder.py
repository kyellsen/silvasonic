"""Startup seeders for Controller — idempotent DB bootstrapping (ADR-0023).

Seeder execution order (recorder-critical first):
    ConfigSeeder → ProfileBootstrapper → ManagedServiceSeeder → CloudSyncSeeder → AuthSeeder

Each seeder runs in its own transaction (per-seeder commit/rollback).
All use INSERT ON CONFLICT DO NOTHING — existing user values are never overwritten.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any, Protocol

import bcrypt
import structlog
import yaml
from pydantic import ValidationError
from silvasonic.controller.worker_registry import SYSTEM_WORKERS
from silvasonic.core.config_schemas import (
    AuthDefaults,
    BirdnetSettings,
    CloudSyncSettings,
    ProcessorSettings,
    SystemSettings,
)
from silvasonic.core.database.models.profiles import MicrophoneProfile as MicProfileDB
from silvasonic.core.database.models.system import ManagedService, SystemConfig, User
from silvasonic.core.schemas.devices import MicrophoneProfile as MicProfileSchema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _find_service_root(start: Path = Path(__file__).resolve()) -> Path:
    """Walk up until pyproject.toml is found."""
    for parent in start.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return start.parent


@cache
def _get_config_dir() -> Path:
    return _find_service_root() / "config"


@cache
def _get_defaults_yml() -> Path:
    return _get_config_dir() / "defaults.yml"


@cache
def _get_profiles_dir() -> Path:
    return _get_config_dir() / "profiles"


def _load_defaults(path: Path) -> dict[str, Any] | None:
    """Load and validate defaults.yml. Returns parsed dict or None."""
    if not path.exists():
        log.warning("seeder.no_defaults_file", path=str(path))
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        log.error("seeder.invalid_yaml", path=str(path))
        return None
    return raw


# ---------------------------------------------------------------------------
# Seeder protocol (static typing only — no runtime_checkable)
# ---------------------------------------------------------------------------


class Seeder(Protocol):
    """Uniform interface for startup seeders (static typing via mypy)."""

    name: str

    async def seed(self, session: AsyncSession) -> None:
        """Seed initial configuration state into the database."""
        ...


# ---------------------------------------------------------------------------
# Individual seeders
# ---------------------------------------------------------------------------


class ConfigSeeder:
    """Seed ``system_config`` with factory defaults (ADR-0023)."""

    name = "config"

    def __init__(
        self,
        defaults_path: Path | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with path to defaults YAML file.

        Args:
            defaults_path: Path to defaults.yml (lazy-loaded when *defaults* is ``None``).
            defaults: Pre-loaded defaults dict.  Takes precedence over *defaults_path*.
        """
        self._defaults_path = defaults_path
        self._defaults = defaults

    async def seed(self, session: AsyncSession) -> None:
        """Load ``defaults.yml`` and insert missing keys into ``system_config``."""
        defaults = self._defaults
        if defaults is None:
            defaults_path = self._defaults_path or _get_defaults_yml()
            defaults = _load_defaults(defaults_path)
        if defaults is None:
            return

        # Only seed keys that have a Pydantic schema mapping.
        # Order matches defaults.yml: cross-cutting first, then by milestone.
        schema_map: dict[str, type] = {
            "system": SystemSettings,
            "processor": ProcessorSettings,
            "cloud_sync": CloudSyncSettings,
            "birdnet": BirdnetSettings,
        }

        for key, value in defaults.items():
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


class ProfileBootstrapper:
    """Seed ``microphone_profiles`` from YAML profile files (ADR-0016)."""

    name = "profiles"

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
            if yml_path.name == ".gitkeep":  # pragma: no cover — coverage artifact
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


class AuthSeeder:
    """Seed default admin user with bcrypt-hashed password (ADR-0023)."""

    name = "auth"

    def __init__(
        self,
        defaults_path: Path | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with path to defaults YAML file.

        Args:
            defaults_path: Path to defaults.yml (lazy-loaded when *defaults* is ``None``).
            defaults: Pre-loaded defaults dict.  Takes precedence over *defaults_path*.
        """
        self._defaults_path = defaults_path
        self._defaults = defaults

    async def seed(self, session: AsyncSession) -> None:
        """Create default admin user if not exists."""
        defaults = self._defaults
        if defaults is None:
            defaults_path = self._defaults_path or _get_defaults_yml()
            defaults = _load_defaults(defaults_path)
        if defaults is None:
            return

        if "auth" not in defaults:
            log.debug("seeder.auth.no_auth_section")
            return

        try:
            auth = AuthDefaults(**defaults["auth"])
        except ValidationError as exc:  # pragma: no cover — defensive
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


class CloudSyncSeeder:
    """Seed cloud sync credentials from environment variables (v0.6.0).

    Reads ``SILVASONIC_CLOUD_REMOTE_TYPE``, ``_URL``, ``_USER``, ``_PASS``
    from the environment.  If ALL four are set, encrypts user/pass via
    Fernet and UPSERTs into ``system_config`` key ``"cloud_sync"``.

    **UPSERT semantics:** ``.env`` is infrastructure — always overwrites
    DB values.  If env vars are absent, the seeder does nothing (existing
    DB values are preserved for Web-UI configuration).
    """

    name = "cloud_sync"

    _ENV_VARS = (
        "SILVASONIC_CLOUD_REMOTE_TYPE",
        "SILVASONIC_CLOUD_REMOTE_URL",
        "SILVASONIC_CLOUD_REMOTE_USER",
        "SILVASONIC_CLOUD_REMOTE_PASS",
    )

    async def seed(self, session: AsyncSession) -> None:
        """Read env vars and UPSERT cloud_sync config if all are present."""
        import os

        values = {v: os.environ.get(v, "").strip() for v in self._ENV_VARS}
        present = {k for k, v in values.items() if v}

        if not present:
            log.debug("seeder.cloud_sync.no_env_vars")
            return

        if present != set(self._ENV_VARS):
            missing = set(self._ENV_VARS) - present
            log.warning(
                "seeder.cloud_sync.partial_env_vars",
                missing=sorted(missing),
                hint="Set ALL four SILVASONIC_CLOUD_REMOTE_* variables or none.",
            )
            return

        # Require encryption key
        try:
            from silvasonic.core.crypto import encrypt_value, load_encryption_key

            encryption_key = load_encryption_key()
        except RuntimeError:
            log.error(
                "seeder.cloud_sync.missing_encryption_key",
                hint=(
                    "SILVASONIC_ENCRYPTION_KEY must be set when cloud credentials "
                    "are provided. Generate with: python -m silvasonic.core.crypto generate-key"
                ),
            )
            return

        remote_type = values["SILVASONIC_CLOUD_REMOTE_TYPE"]
        remote_url = values["SILVASONIC_CLOUD_REMOTE_URL"]
        remote_user = values["SILVASONIC_CLOUD_REMOTE_USER"]
        remote_pass = values["SILVASONIC_CLOUD_REMOTE_PASS"]

        # Build remote_config with encrypted credentials
        remote_config: dict[str, Any] = {
            "url": remote_url,
            "user": encrypt_value(remote_user, encryption_key),
            "pass": encrypt_value(remote_pass, encryption_key),
        }

        # Auto-detect Nextcloud vendor for WebDAV
        if remote_type == "webdav" and (
            "nextcloud" in remote_url.lower() or remote_url.rstrip("/").endswith("/webdav")
        ):
            remote_config["vendor"] = "nextcloud"

        # Validate the settings
        try:
            validated = CloudSyncSettings(
                enabled=True,
                remote_type=remote_type,
                remote_config=remote_config,
            )
        except ValidationError as exc:
            log.error(
                "seeder.cloud_sync.validation_failed",
                errors=exc.error_count(),
            )
            return

        cloud_sync_value = validated.model_dump()

        # UPSERT: .env is infrastructure, always overwrites
        existing = await session.get(SystemConfig, "cloud_sync")
        if existing is not None:
            # Merge: keep non-credential settings (poll_interval, bandwidth, schedule),
            # overwrite remote_type, remote_config, and enable.
            merged = dict(existing.value)
            merged["enabled"] = True
            merged["remote_type"] = remote_type
            merged["remote_config"] = remote_config
            existing.value = merged
            log.info(
                "seeder.cloud_sync.upserted",
                remote_type=remote_type,
                action="updated",
            )
        else:
            session.add(SystemConfig(key="cloud_sync", value=cloud_sync_value))
            log.info(
                "seeder.cloud_sync.upserted",
                remote_type=remote_type,
                action="inserted",
            )


class ManagedServiceSeeder:
    """Seed ``managed_services`` with Tier-2 singleton workers (ADR-0029).

    Only Tier-2 containers orchestrated by the Controller belong here.
    Tier-1 services (processor, controller) are managed externally via
    Compose and MUST NOT be seeded.
    """

    name = "managed_services"

    async def seed(self, session: AsyncSession) -> None:
        """Insert default managed_services rows (ON CONFLICT DO NOTHING)."""
        for worker in SYSTEM_WORKERS:
            name = worker.name
            # Default to enabled for all registered workers
            enabled = True

            existing = await session.get(ManagedService, name)
            if existing is None:
                session.add(ManagedService(name=name, enabled=enabled))
                log.info("seeder.managed_service.inserted", name=name, enabled=enabled)
            else:
                log.debug("seeder.managed_service.skipped", name=name)


async def run_all_seeders(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[str]:
    """Run all seeders with per-seeder transaction isolation.

    Returns list of failed seeder names (empty on full success).

    Seeder order: recorder-critical first, then infrastructure, then optional.
    ConfigSeeder and ProfileBootstrapper MUST run first because
    ``ProfileMatcher`` reads ``system.auto_enrollment`` and profiles
    during the Initial Device Scan that follows immediately after seeding.
    """
    defaults = _load_defaults(_get_defaults_yml())

    # Order: recorder-critical first, then infrastructure, then optional.
    seeders: list[Seeder] = [
        ConfigSeeder(defaults=defaults),
        ProfileBootstrapper(),
        ManagedServiceSeeder(),
        CloudSyncSeeder(),
        AuthSeeder(defaults=defaults),
    ]

    log.info("seeder.start", count=len(seeders))
    failed: list[str] = []

    for seeder in seeders:
        async with session_factory() as session:
            try:
                await seeder.seed(session)
                await session.commit()
                log.info("seeder.completed", seeder=seeder.name)
            except Exception:
                await session.rollback()
                log.exception("seeder.failed", seeder=seeder.name)
                failed.append(seeder.name)

    if failed:
        log.warning("seeder.partial_failure", failed=failed)
    else:
        log.info("seeder.all_complete")

    return failed
