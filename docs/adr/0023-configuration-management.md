# ADR-0023: Configuration Management — YAML Seed, DB Settings, Users Table

> **Status:** Accepted • **Date:** 2026-02-23

## 1. Context & Problem

Silvasonic services need configuration at three levels:

1.  **Infrastructure** — paths, hostnames, sockets (must exist *before* any container starts).
2.  **Application Settings** — latitude/longitude, polling intervals, retention thresholds, bandwidth limits (tunable at runtime via Web-Interface).
3.  **Authentication** — user credentials for the Web-Interface login.

Without a clear strategy, configuration is scattered across `.env`, hardcoded Python defaults, and undocumented database rows. New deployments have no reproducible initial state, and there is no single place to define what "factory defaults" look like.

## 2. Decision

**We chose:** A three-tier configuration architecture with a YAML seed file for reproducible initial state.

### 2.1. Configuration Tiers

| Tier                     | Storage                       | Examples                                                                 | Set By                    | Runtime Changeable?                       |
| ------------------------ | ----------------------------- | ------------------------------------------------------------------------ | ------------------------- | ----------------------------------------- |
| **Infrastructure**       | `.env` file                   | `SILVASONIC_WORKSPACE_PATH`, `SILVASONIC_DB_HOST`, `SILVASONIC_PODMAN_SOCKET` | Admin (SSH / Ansible)     | No — requires container rebuild/restart   |
| **Application Settings** | `settings` table (JSONB) | `latitude`, `max_microphones`, `min_confidence`, `bandwidth_limit_bytes_per_s`   | YAML Seed → Web-Interface | Yes — via State Reconciliation (ADR-0017) |
| **Authentication**       | `users` table                 | `username`, `password_hash`                                              | YAML Seed → Web-Interface | Yes — Frontend settings page              |

### 2.2. Application Settings — `settings` Table

The `settings` table (section TEXT, value JSONB, revision INTEGER) stores all application settings as one JSON blob per section; `revision` starts at 1 and grows with every write:

| Section     | Pydantic Schema     | Used By                                                                            |
| ----------- | ------------------- | ---------------------------------------------------------------------------------- |
| `station`   | `StationSettings`   | All services (station id, name, latitude, longitude)                               |
| `recording` | `RecordingSettings` | Controller (auto_enrollment, max_microphones)                                      |
| `storage`   | `StorageSettings`   | Processor (Janitor thresholds, Indexer intervals)                                  |
| `sync`      | `SyncSettings`      | Processor Cloud-Sync-Worker (polling, bandwidth, upload window, remote target). The on/off switch is the `cloud_sync` row of the `modules` table. |
| `birdnet`   | `BirdnetSettings`   | BirdNET runtime settings (min_confidence, overlap_s, sensitivity). Lifecycle toggle (`enabled`) is managed separately in `modules` table (ADR-0029). |

Each section maps to a Pydantic `BaseModel` that defines field types and default values. Historically, services read their settings **once on startup** (Immutable Container pattern). However, under the newer **Hybrid Tier-2 Architecture**, workers like BirdNET dynamically poll their relevant `settings` sections (e.g., sensitivity, thresholds) at safe loop boundaries via Snapshot Refresh. This allows the Web-Interface to adjust parameters on-the-fly without requiring the Controller to restart the affected service. See [ADR-0031](0031-runtime-tuning-snapshot-refresh.md) for the field classification matrix and implementation details.

### 2.3. YAML Seed File — `config/defaults.yml`

A version-controlled YAML file defines factory defaults for all `settings` sections:

```yaml
# config/defaults.yml — seeded into settings on Controller startup
station:
  name: "Silvasonic Dev"
  latitude: null
  longitude: null

recording:
  auto_enrollment: true   # Auto-enroll devices with exact profile match (runtime-changeable)
  max_microphones: 5

auth:
  default_username: "admin"
  default_password: "silvasonic"  # MUST be changed in production!

# Service settings are added here when each service is implemented:
# storage:                             # v0.5.0
#   warning_percent: 70.0
#   ...
# sync:                                # v0.6.0
#   ...
# birdnet:                             # v0.8.0
#   min_confidence: 0.65
```

**Seeding behavior:**
1.  On every Controller startup, the YAML is loaded and validated against Pydantic schemas.
2.  The Controller inserts each section into `settings` via Python (`INSERT ... ON CONFLICT DO NOTHING`). No SQL seed files.
3.  Existing user-modified values are **never overwritten**.
4.  After a database reset, all defaults are restored automatically on the next Controller startup.
5.  Service settings are only seeded once the corresponding service is implemented and uncommented in the YAML.

### 2.3.1 Local Developer Override

To prevent "volatile DBs" (e.g. from frequent `just nuke` workflows) from repeatedly wiping developer customizations without polluting the Git tree with `.env` application state (which violates section 2.6):
Developers may create a `config/defaults.override.yml` file. This file is ignored by `.gitignore`.
If present during Controller startup, the ConfigSeeder performs a deep-merge of this override file *over* the `defaults.yml`. This ensures that local values consistently re-seed into fresh databases while maintaining strict ADR-0023 tier compliance.

### 2.4. Authentication — `users` Table

Authentication credentials are stored in a **dedicated `users` table**, separate from `settings`:

```sql
CREATE TABLE users (
    id       UUID NOT NULL DEFAULT uuidv7() PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Rationale:** Credentials have a fundamentally different structure (username + bcrypt hash) and lifecycle (RBAC readiness for v1.9.0+) than settings sections. A separate table keeps the schema clean and enables future multi-user support without schema changes.

**Seeding:** A default admin account is seeded from the `auth` section of `config/defaults.yml` by the Controller on startup. The password is hashed with bcrypt before insertion. Production deployments must change the default password via the Web-Interface settings page.

### 2.5. Pydantic Validation — `schemas/settings.py`

All configuration blobs are parsed and validated via Pydantic `BaseModel` classes in `silvasonic.core.schemas.settings`. This ensures:

*   Type safety (latitude must be a float, max_microphones must be an int).
*   Defaults are defined in one place (the schema), mirrored in the YAML seed.
*   Invalid configuration is caught at startup, not at runtime.

### 2.6. What Does NOT Go in `settings`

| Category                      | Where                   | Why                                |
| ----------------------------- | ----------------------- | ---------------------------------- |
| Host paths (`WORKSPACE_PATH`) | `.env`                  | Required before DB is reachable    |
| DB credentials                | `.env`                  | Required to connect to DB          |
| Redis host                    | `.env`                  | Required before Redis is reachable |
| Podman socket path            | `.env`                  | Infrastructure prerequisite        |
| User passwords                | `users` table           | Different structure, RBAC-ready    |
| Cloud storage credentials     | `settings` section `sync` | Fernet-encrypted (`enc:` prefix) in `SyncSettings.remote_config` (v0.6.0) |
| Encryption key                | `.env`                  | `SILVASONIC_ENCRYPTION_KEY` — Fernet key for cloud credential encryption |

> [!IMPORTANT]
> **Lifecycle toggles** (`enabled: bool`) for Controller-managed Tier-2 containers (BirdNET, BatDetect, Weather) belong in the `modules` table, **NOT** in `settings`. The `settings` table stores exclusively domain/business settings. See [ADR-0029](0029-system-worker-orchestration.md).

## 3. Options Considered

*   **SQL-only seed (`INSERT` statements):** Rejected. SQL is unwieldy for nested JSON defaults, hard to review/diff, and creates a second seeding path alongside YAML. All seeding goes through Python for consistency.
*   **Pydantic defaults only (no YAML file):** Rejected. Defaults would be scattered across multiple Python files. A single YAML is the canonical source.
*   **Flat columns instead of JSONB:** Rejected. Adding a new setting would require a schema migration. JSONB + Pydantic validation gives the same type safety with zero migration cost.
*   **Auth in `settings`:** Rejected. Credentials need their own table structure (username, hash, active) and will grow into RBAC later.

## 4. Consequences

*   **Positive:**
    *   One YAML file defines all factory defaults — reproducible, version-controlled, diff-friendly.
    *   Pydantic ensures type safety without relying on database constraints.
    *   User modifications survive Controller restarts (seed uses `ON CONFLICT DO NOTHING`).
    *   `users` table is RBAC-ready for v1.9.0+ without schema changes.
    *   `.env` stays minimal — only true infrastructure prerequisites.
*   **Negative:**
    *   Two sources of truth for defaults (YAML + Pydantic). Must stay in sync manually. Mitigation: CI test validates YAML against schemas.
    *   Adding a new settings key requires updating YAML, Pydantic schema, and the Controller seed logic.
