# Database Schema

This document defines the database schema for the Silvasonic Bioacoustic Monitoring System.
The system uses **PostgreSQL** with the **TimescaleDB** extension for time-series optimization.

> **Note:** All tables reside in the `public` schema.

## 1. Core Data Tables

These tables store the primary bioacoustic data. `detections` and `weather` are optimized as TimescaleDB hypertables.

### `recordings`
The central registry of all audio files recorded by the system.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` | Primary Key. |
| `time` | `TIMESTAMPTZ` | Recording start time. Indexed. |
| `sensor_id` | `TEXT` | Microphone Identifier. Foreign Key to `devices.name`. |
| `file_raw` | `TEXT` | Relative path (e.g. `front/2024...wav`). **Raw/Native** (Variable Rate). |
| `file_processed` | `TEXT` | Relative path (e.g. `front/2024...wav`). **Processed/Standardized (48kHz)**. |
| `duration` | `FLOAT` | Duration in seconds. |
| `sample_rate` | `INTEGER` | Native Sample rate in Hz (of the Raw file). |
| `filesize_raw` | `BIGINT` | Size of Raw file in bytes. |
| `filesize_processed` | `BIGINT` | Size of Processed file in bytes. |
| `uploaded` | `BOOLEAN` | Sync status (High-res archive). Default `false`. Indexed. |
| `uploaded_at` | `TIMESTAMPTZ` | Timestamp of successful upload. Nullable. |
| `analysis_state` | `JSONB` | flexible map of analysis status (e.g. `{"birdnet": true, "batdetect": false}`). |

### `detections`
Stores analysis results from various workers (BirdNET, etc.).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` | Primary Key (Composite). |
| `time` | `TIMESTAMPTZ` | **Partition Key** + Primary Key (Composite). Detection start time. |
| `end_time` | `TIMESTAMPTZ` | Detection end time. Allows efficient duration/overlap queries. |
| `recording_id` | `BIGINT` | Foreign Key to `recordings.id`. |
| `worker` | `TEXT` | Name of the analysis worker (e.g., `birdnet`). Indexed. |
| `confidence` | `FLOAT` | Confidence score (0.0 - 1.0). **Core Metric**. |
| `label` | `TEXT` | Normalized Label (Scientific Name or ID). Key for Taxonomy. Indexed. |
| `common_name` | `TEXT` | Standard English Name (e.g. "Blackbird"). Fast search/display. |
| `details` | `JSONB` | Raw metadata (e.g. `{"box": [...]}`). |

### `taxonomy`
Metadata registry for all detection classes (Bio- & Anthropophony).
Maps raw labels to human-readable info ("Pokedex").

| Column | Type | Description |
| :--- | :--- | :--- |
| `worker` | `TEXT` | Primary Key (Composite). e.g., `birdnet`. |
| `label` | `TEXT` | Primary Key (Composite). The raw label from detections. |
| `scientific_name` | `TEXT` | Latin Name or System ID (e.g. *Stihl MS 500i* or *Turdus*). |
| `common_names` | `JSONB` | Localized names (e.g. `{"de": "Amsel", "en": "Blackbird"}`). |
| `description` | `JSONB` | Localized descriptions (e.g. `{"de": "...", "en": "..."}`). |
| `image_path` | `TEXT` | Path to local file (e.g. `/static/taxonomy/turdus_merula.jpg`). **Served by Nginx/FastAPI**. |
| `image_source` | `TEXT` | Origin URL (Wikimedia) for attribution and refetching. |
| `conservation_status` | `TEXT` | IUCN Red List status (e.g., `LC`, `EN`). |

### `weather`
Hybrid environmental data from local sensors (BME280) and external APIs (OpenMeteo).

| Column | Type | Description |
| :--- | :--- | :--- |
| `time` | `TIMESTAMPTZ` | **Partition Key** + Primary Key (Composite). Measurement time. |
| `source` | `TEXT` | Primary Key (Composite). Data source origin (e.g., `local_bme280`, `openmeteo`). |
| `station_code` | `TEXT` | External Station ID (e.g., DWD `10865` or ICAO `EDDM`). Null for local. |
| `temp_c` | `FLOAT` | Temperature in °C. |
| `humidity` | `FLOAT` | Relative Humidity in %. |
| `pressure_hpa` | `FLOAT` | Pressure in hPa. |
| `wind_speed_kmh` | `FLOAT` | Wind speed (usually from API). |
| `wind_gusts_kmh` | `FLOAT` | Max gust speed. |
| `precipitation_mm` | `FLOAT` | Rain/Precipitation volume. |
| `cloud_cover` | `INTEGER` | Cloud coverage percentage (0-100). |
| `uv_index` | `FLOAT` | UV Index (0-11+). |
| `sunshine_duration` | `FLOAT` | Duration of sunshine in seconds (per interval). |
| `weather_code` | `INTEGER` | WMO Weather Code (e.g., 0=Clear, 61=Rain). |
| `is_forecast` | `BOOLEAN` | `true` if this was a forecast, `false` if measured/historical. Default `false`. |
| `extra` | `JSONB` | **Overflow Buffer**. Stores unforeseen sensor metrics (e.g. Soil Moisture, Lux) without schema migration. |

## 2. Control Plane Tables

These tables manage the system state and configuration. They are standard PostgreSQL tables.

### `system_services`
Registry of dynamic services managed by the Controller.

| Column | Type | Description |
| :--- | :--- | :--- |
| `name` | `TEXT` | Primary Key. Service name (e.g., `birdnet`). |
| `enabled` | `BOOLEAN` | Target state (Intent). Default `true`. |
| `status` | `TEXT` | Current status (e.g., `running`, `stopped`). Default `stopped`. |

### `system_config`
Global Key-Value store for application settings.

| Column | Type | Description |
| :--- | :--- | :--- |
| `key` | `TEXT` | Primary Key. Configuration key. |
| `value` | `JSONB` | Configuration value. |

### `devices`
Inventory of hardware devices (microphones, potential other sensors). Allows stateful management and frontend configuration.

| Column | Type | Description |
| :--- | :--- | :--- |
| `name` | `TEXT` | Primary Key. Hardware ID (e.g. `front`, `back`). Referenced by `recordings.sensor_id`. |
| `serial_number` | `TEXT` | Unique hardware serial (e.g. `123456`). Used for binding. |
| `model` | `TEXT` | Hardware model info (e.g. `Dodotronic Ultramic 384 EVO`). |
| `status` | `TEXT` | Current state (e.g. `online`, `offline`, `error`). Default `offline`. |
| `last_seen` | `TIMESTAMPTZ` | Timestamp of last heartbeat/connection. |
| `enabled` | `BOOLEAN` | User-controllable switch to enable/disable this input. Default `true`. |
| `config` | `JSONB` | Device-specific configuration (e.g., gain, sample rate targets). |

## 3. Audit Tables

### `uploads`
Immutable audit log of all upload attempts (successful or failed).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` | Primary Key. |
| `recording_id` | `BIGINT` | Foreign Key to `recordings.id`. |
| `attempt_at` | `TIMESTAMPTZ` | Time of the upload attempt. |
| `filename` | `TEXT` | Name of the file. |
| `size` | `BIGINT` | Bytes transferred. |
| `success` | `BOOLEAN` | Outcome of the attempt. |
| `error_message` | `TEXT` | Error details if failed. |

## 4. TimescaleDB Configuration

- **Chunk Time Interval**: 24 hours (for `detections`, `weather`).
- **Retention Policy**: Managed by `Janitor` service (see `filesystem_governance.md`).

### Performance Tuning (Raspberry Pi 5 + NVMe)
Optimized for write throughput on NVMe storage.

- `synchronous_commit = off`: Speed > Safety (minor data loss risk on crash accepted).
- `shared_buffers = 512MB`: ~12% of 4GB RAM.
- `random_page_cost = 1.1`: Optimized for NVMe random access.

## 5. Data Governance & Model Strategy

> **Strategy:** Single Public Schema.
> **Consistency:** All containers MUST import SQL models from the shared library **`packages/core`** (e.g., `silvasonic.core.database`). 
> **Constraint:** Ad-hoc SQL tables defined within individual service code are **FORBIDDEN**.

### Why this approach?
See [ADR 0013: Shared Core Library](../adr/0013-shared-core-library.md).
- **Single Source of Truth**: Ensures `recorder` and `dashboard` agree on data types.
- **Migration Safety**: Centralized `alembic` migrations (in `core` or `infrastructure` container) prevent schema drift.
- **Type Sharing**: Pydantic models in `core` allow typing to flow from DB to API to Frontend.

## 6. Initialization Strategy

To avoid "Chicken-and-Egg" problems, initialization is split into two phases:

### Phase 1: Infrastructure (`docker-entrypoint-initdb.d/init.sql`)
*   **When:** Runs ONLY when the database volume is first created.
*   **Responsibility:** "God-Mode" setup that requires superuser privileges.
*   **Content:**
    ```sql
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    -- No tables defined here!
    ```

### Phase 2: Schema (`alembic upgrade head`)
*   **When:** Runs on every container startup (via `controller` or `pre-start` hooks).
*   **Responsibility:** Creating tables, modifying columns, managing indexes.
*   **Mechanism:** Uses the `packages/core` Python definitions to apply changes incrementally.
*   **Benefit:** Allows the schema to evolve (e.g., adding `devices` table) without wiping the database.
