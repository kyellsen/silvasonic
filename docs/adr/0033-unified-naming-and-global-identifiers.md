# ADR-0033: Unified Naming and Global Identifiers

> **Status:** Proposed • **Date:** 2026-11-10

## 1. Context & Problem

The API contract ([ADR-0032](0032-api-first-station-contract.md)) names things for clients that cannot be renamed later. Today's schema is not ready to be that vocabulary:

*   **Identifiers collide across stations.** `recordings.id`, `detections.id` and `uploads.id` count from 1 on every station. A fleet server that collects a thousand stations would have a thousand recordings number 1. A detection is addressed by `(time, id)`.
*   **One concept has several names.** A microphone is a `device`, its key is `name`, a recording points to it as `sensor_id`. An analysis service is a `worker` in `detections` and a row in `managed_services`. Settings live in `system_config` under `system`, and once under `system_settings`.
*   **Names hide what a value is.** `time`, `duration`, `sample_rate` and `size` carry no unit and no role. `local_deleted` cannot say when. `analysis_state` holds free text such as `crashed: …`.
*   **"Device" will be ambiguous.** In fleet language the device is the station.

No station has collected data worth keeping. Renaming now costs a refactoring; renaming after the first release costs a migration on every station and a new API version.

## 2. Decision

**We chose:** one name per concept — identical in the database column, the Pydantic field, the API field and the interface — and identifiers that are unique across all stations. The schema is changed once, in place, before the API is implemented.

**Reasoning:**

*   **Global identifiers.** Rows created at runtime get a UUIDv7 `id`: recordings, detections, uploads, microphones, users, sessions, tokens, events, alerts. It is unique without a central authority, sorts by creation time and keeps indexes compact. The database generates it (`DEFAULT uuidv7()`; a polyfill of that name until the database image moves to PostgreSQL 18, which has it built in). Authored entities keep readable slugs: microphone profiles, species, modules, settings sections. A station generates its own UUIDv7 at first boot.
*   **Detections keep their hypertable key** `(started_at, id)`, which TimescaleDB requires, and gain an index on `id` so that the API addresses a detection by `id` alone.
*   **Naming rules**, applied everywhere:

    | Rule | Example |
    | --- | --- |
    | A point in time ends in `_at` | `started_at`, `deleted_at` |
    | A quantity carries its unit | `duration_s`, `sample_rate_hz`, `size_bytes`, `used_percent` |
    | A reference ends in `_id` and names its target | `microphone_id`, `species_id` |
    | A lifecycle field ends in `_state` and holds a fixed set of values | `connection_state`, `review_state` |
    | A boolean is an adjective, without `is_` | `enabled`, `built_in`, `clock_synced` |
    | A fact is stored once | `uploaded_at` replaces `uploaded` + `uploaded_at` |
    | A path is internal | columns end in `_path`; the API shows URLs |

*   **"Microphone" replaces "Device"**, and "Station" names the whole unit. "Analyzer" names what produced a detection; "Module" names an optional feature the user switches, whichever process implements it.

### Rename map

| Today | Becomes | Why |
| --- | --- | --- |
| table `devices` | `microphones` | "device" means the station in a fleet |
| `devices.name` (the Stable Device ID, primary key) | `hardware_id` (unique); new `id` (UUIDv7, primary key); new `name` (label chosen by the user) | the key leaks USB IDs and is not unique across stations; users want to name microphones |
| `devices.status` (`online`/`offline`) | `connection_state` (`connected`/`disconnected`) | says which state |
| `devices.enrollment_status` | `enrollment_state` | `_state` rule |
| `devices.last_seen` | `last_seen_at`; new `first_seen_at` | `_at` rule |
| `devices.config` | `hardware` | it holds what was read from the device, not configuration |
| `microphone_profiles.is_system` | `built_in` | boolean rule |
| `microphone_profiles.match_pattern`, `audio.match_pattern` | removed | legacy, replaced by `audio.match` |
| profile `audio.sample_rate`, `audio.format`, `processing.chunk_size` | `sample_rate_hz`, `sample_format`, `chunk_frames` | unit rule |
| `recordings.id` (bigint) | `id` (UUIDv7) | global identifier |
| `recordings.time` | `started_at` | it is the first sample |
| `recordings.sensor_id` → `devices.name` | `microphone_id` → `microphones.id` | one name per concept |
| `recordings.file_raw`, `file_processed` | `raw_path`, `processed_path` | path rule |
| `recordings.duration` | `duration_s` | unit rule |
| `recordings.sample_rate` (rate of the indexed file) | `sample_rate_hz` (native rate of the microphone); new `channels` | today the native rate of a dual-stream recording is stored nowhere |
| `recordings.filesize_raw`, `filesize_processed` | `raw_size_bytes`, `processed_size_bytes` | unit rule |
| `recordings.uploaded` | removed; `uploaded_at` says it | stored once |
| `recordings.local_deleted` | `deleted_at`, `deletion_reason` | the deletion log needs the time and the cause |
| `recordings.clock_unsynced` | `clock_synced` (default `true`) | boolean rule: no negated names |
| `recordings.analysis_state` (`{"birdnet": "crashed: …"}`) | `{"birdnet": {"state": …, "reason": …, "finished_at": …}}` with states `done`, `failed`, `skipped` | a client must be able to branch on it |
| `detections.id` (bigint) | `id` (UUIDv7) | global identifier |
| `detections.time`, `end_time` | `started_at`, `ended_at` | `_at` rule |
| `detections.worker` | `analyzer` | "worker" is how it runs, not what it is |
| `detections.label`, `common_name` | `label` (as the analyzer reported it) and new `species_id`; `common_name` removed | names belong to the species |
| — | `detections.review_state`, `corrected_species_id`, `review_note`, `reviewed_at`, `reviewed_by` | review of detections |
| table `taxonomy`, key `(worker, label)` | `species`, key `id` (slug of the scientific name); `analyzer` + `label` unique; new `category`, `watched` | the API resource; non-species sound classes get a category |
| `taxonomy.description` | `descriptions` | a dictionary by language, like `common_names` |
| `uploads.id`, `attempt_at`, `size` | `id` (UUIDv7), `attempted_at`, `size_bytes` | rules above |
| table `managed_services` | `modules`; `cloud_sync.enabled` moves here | one place for "is this feature switched on" |
| table `system_config`, column `key` | `settings`, column `section`; new `revision` | the API resource; `revision` backs `If-Match` |
| section `system` | `station` (`id`, `name`, `latitude`, `longitude`, `elevation_m`, `timezone`, `language`) and `recording` (`auto_enrollment`, `max_microphones`) | identity apart from behaviour |
| section `processor` | `storage` (`warning_percent`, `critical_percent`, `emergency_percent`, `max_age_days`) | named after what the user sets |
| section `cloud_sync` | `sync` (`bandwidth_limit_bytes_per_s`, `window`); the target becomes its own record with an encrypted secret | unit rule; secrets apart from settings |
| `birdnet.confidence_threshold`, `overlap`, `clip_padding_seconds` | `min_confidence`, `overlap_s`, `clip_padding_s` | unit rule |
| section `auth` (default credentials) | removed | [ADR-0034](0034-authentication-and-authorization.md) |
| `users.id` (bigint), `is_active` | `id` (UUIDv7), `active`; new `role`, `display_name`, `language`, `last_login_at` | [ADR-0034](0034-authentication-and-authorization.md) |
| table `weather`, `time`, `temp_c`, `humidity`, `cloud_cover`, `sunshine_duration`, `is_forecast` | `weather_observations`, `observed_at`, `temperature_c`, `humidity_percent`, `cloud_cover_percent`, `sunshine_duration_s`, `forecast` | glossary term; rules above |
| — | new tables `sessions`, `api_tokens`, `events`, `alerts`, `audit_log`, `sync_target` | state the API needs |

Operational tuning that no user sets (`indexer_poll_interval`, `janitor_batch_size`, `threads`) follows the unit rule and stays outside the API. Redis keys and heartbeat payloads remain internal contracts in `silvasonic.core.schemas`; the API translates them into `components`.

## 3. Options Considered

*   **Translate names in the API only:** Rejected. Two vocabularies for one concept is the state this ADR ends; every query and every bug report would need the dictionary.
*   **Keep bigint, address rows as `(station_id, id)`:** Rejected. Every reference in every client and export would be a pair, and a row moved between systems would need both halves rewritten.
*   **UUIDv4:** Rejected. Random keys scatter index writes and say nothing about order.
*   **ULID:** Rejected. Same properties as UUIDv7 without a native database type.
*   **Rename later, with a migration:** Rejected. It would need a migration on every station and a second API version for a change that is free today.

## 4. Consequences

*   **Positive:**
    *   A field means the same thing in a query, a log line, an API response and the interface.
    *   Data of many stations merges without rewriting keys.
    *   The contract can stay stable because its names were chosen on purpose.
*   **Negative:**
    *   One refactoring across the schema, the ORM models, all services, the microphone profile YAML and the tests. Existing development databases are recreated.
    *   UUIDs are 16 bytes where bigint was 8.
*   **This is the last change made by editing the init schema.** From the first release on, a schema change needs a versioned migration, because stations in the field cannot be recreated. The tool is decided in its own ADR before v1.0.0.
*   **On acceptance these documents change:** `docs/glossary.md` (Microphone, Station, Analyzer, Module, Species replace or join Device, Managed Service, Taxonomy), ADR-0011 (`_unsynced` marker ↔ `clock_synced`), ADR-0023 and ADR-0029 (table names), the service READMEs that name tables.
