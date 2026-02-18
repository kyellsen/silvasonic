# ADR-0016: Hybrid YAML/DB Profile Management

> **Status:** Accepted • **Date:** 2026-02-18

## 1. Context & Problem
Silvasonic requires precise configuration for audio hardware ("Microphone Profiles") to ensure scientific-grade recordings:
*   **Stability:** We ship "known good" profiles for supported hardware (e.g., Dodotronic Ultramic, generic USB) that must work out-of-the-box.
*   **Flexibility:** Users may bring custom hardware or experimental microphones that need custom profiles without rebuilding container images.
*   **Dynamic Editing:** The Web-Interface (Tier 1, future) needs to create or edit profiles at runtime via the Controller API.

Previously, profiles were loaded directly from YAML files at startup. This made dynamic editing impossible without complex file editing capabilities inside the container.

> **Related Decisions:**
> *   **[ADR-0005](0005-two-worlds-separation.md):** YAML seed files in the repository = World A (immutable code). DB state = World B (mutable state). This ADR is a concrete application of the Two-Worlds principle.
> *   **[ADR-0012](0012-use-pydantic.md):** The `config` JSONB field is validated via Pydantic V2 models.
> *   **[ADR-0013](0013-tier2-container-management.md):** The Recorder receives its profile configuration via Profile Injection (environment variables). The Recorder itself has **no database access**.

## 2. Decision
**We chose:** A Hybrid YAML-to-Database Bootstrapping model.

**Reasoning:**

1.  **Database is the Single Source of Truth at Runtime:**
    *   The Controller reads profiles exclusively from the `microphone_profiles` database table.
    *   The Recorder never accesses the database — it receives its configuration via Profile Injection (environment variables set by the Controller at container creation time, see ADR-0013).
    *   The Web-Interface (future) can trivially CRUD profiles via the Controller API.

2.  **YAML Files as Seed Data:**
    *   System-default profiles are maintained as YAML files in the repository (`services/recorder/config/profiles/`).
    *   YAML files MUST be parsed using `pyYAML` with strict `safe_load` (see AGENTS.md §5).
    *   On every Controller startup, a `ProfileBootstrapper`:
        *   Reads the YAML files.
        *   **Upserts** (Insert or Update) them into the database.
        *   Marks them as `is_system=True`.
    *   This ensures "Repo is Truth" for system profiles — changes in the git repository automatically propagate to deployments on update/restart.

3.  **Strict Device Linking:**
    *   The `devices` table has a Foreign Key (`profile_slug`) to `microphone_profiles.slug`.
    *   Profile configuration is stored as validated JSONB (Pydantic V2) rather than loosely in a JSON column on the device.

### 2.1. Implementation Status
The database schema is implemented:
*   SQLAlchemy model: [`profiles.py`](../../packages/core/src/silvasonic/core/database/models/profiles.py) — `microphone_profiles` table with `slug`, `name`, `description`, `match_pattern`, `config` (JSONB), `is_system` (Boolean).
*   Device FK: [`system.py`](../../packages/core/src/silvasonic/core/database/models/system.py) — `devices.profile_slug → microphone_profiles.slug`.

The ProfileBootstrapper and YAML seed files are planned but not yet implemented.

## 3. Options Considered
*   **YAML-Only (No Database):**
    *   *Rejected because:* Makes runtime editing (Requirement 3) impossible without file-editing capabilities inside immutable Tier 2 containers.
*   **Database-Only (No YAML Seeds):**
    *   *Rejected because:* Loses GitOps compatibility — system profiles would not be version-controlled and deployments would require manual database seeding.
*   **Configuration via Environment Variables Only:**
    *   *Rejected because:* Profiles contain complex nested configuration (sample rates, channel mappings, match patterns) that is impractical to express as flat environment variables.

## 4. Consequences
*   **Positive:**
    *   **API Ready:** The Controller can expose CRUD endpoints for user-defined profiles via the Web-Interface.
    *   **GitOps Compatible:** Changes to system profiles in the repository automatically propagate on Controller restart.
    *   **Data Integrity:** Foreign keys prevent deleting a profile that is in use by a device.
    *   **Two-Worlds Alignment:** Seed data (World A) bootstraps runtime state (World B).
*   **Negative:**
    *   **Precedence Complexity:** YAML "wins" on startup — the bootstrapper overwrites DB changes to system profiles (`is_system=True`). This is intentional to enforce "Repo is Truth" for system profiles. User-created profiles (`is_system=False`) are never overwritten.
    *   **Startup Penalty:** Small overhead to parse YAMLs and sync to PostgreSQL on every boot (negligible for expected profile counts < 100).

## 5. References
*   [Microphone Profiles Documentation](../arch/microphone_profiles.md)
*   [Glossary — Microphone Profile](../glossary.md)
