# Database Schema

This document defines the database schema for the Silvasonic Bioacoustic Monitoring System.
The system uses **PostgreSQL** with the **TimescaleDB** extension for time-series optimization.

> **Note:** All tables reside in the `public` schema.

## 1. Core Data Tables

These tables store the primary bioacoustic data and are optimized as TimescaleDB hypertables.

### `recordings`
The central registry of all audio files recorded by the system.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` | Primary Key. |
| `time` | `TIMESTAMPTZ` | **Partition Key**. Recording start time. |
| `filename_high` | `TEXT` | High-Res (384kHz) filename (Archive). |
| `filename_low` | `TEXT` | Low-Res (48kHz) filename (Analysis/Proxy). |
| `duration` | `FLOAT` | Duration in seconds. |
| `sample_rate` | `INTEGER` | Native Sample rate in Hz (High-Res). |
| `filesize_high` | `BIGINT` | Size of High-Res file in bytes. |
| `filesize_low` | `BIGINT` | Size of Low-Res file in bytes. |
| `uploaded` | `BOOLEAN` | Sync status (High-res archive). Default `false`. |
| `uploaded_at` | `TIMESTAMPTZ` | Timestamp of successful upload. Nullable. |
| `analyzed_bird` | `BOOLEAN` | BirdNET analysis status. Default `false`. |
| `analyzed_bat` | `BOOLEAN` | Bat analysis status. Default `false`. |

### `detections`
Stores analysis results from various workers (BirdNET, etc.).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` | Primary Key. |
| `time` | `TIMESTAMPTZ` | **Partition Key**. Detection time (offset from recording start). |
| `recording_id` | `BIGINT` | Foreign Key to `recordings.id`. |
| `worker` | `TEXT` | Name of the analysis worker (e.g., `birdnet`). |
| `confidence` | `FLOAT` | Confidence score (0.0 - 1.0). |
| `label` | `TEXT` | Species or event label. |
| `details` | `JSONB` | Worker-specific metadata (e.g., frequency range). |

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
| `image_url` | `TEXT` | Reference to a locally stored or remote image. |
| `conservation_status` | `TEXT` | IUCN Red List status (e.g., `LC`, `EN`). |

### `weather`
Hybrid environmental data from local sensors (BME280) and external APIs (OpenMeteo).

| Column | Type | Description |
| :--- | :--- | :--- |
| `time` | `TIMESTAMPTZ` | **Partition Key**. Measurement time. |
| `source` | `TEXT` | Data source origin (e.g., `local_bme280`, `openmeteo`). |
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
| `is_forecast` | `BOOLEAN` | `true` if this was a forecast, `false` if measured/historical. |
| `extra` | `JSONB` | **Overflow Buffer**. Stores unforeseen sensor metrics (e.g. Soil Moisture, Lux) without schema migration. |

## 2. Control Plane Tables

These tables manage the system state and configuration. They are standard PostgreSQL tables.

### `system_services`
Registry of dynamic services managed by the Controller.

| Column | Type | Description |
| :--- | :--- | :--- |
| `name` | `TEXT` | Primary Key. Service name (e.g., `birdnet`). |
| `enabled` | `BOOLEAN` | Target state (Intent). |
| `status` | `TEXT` | Current status (e.g., `running`, `stopped`). |

### `system_config`
Global Key-Value store for application settings.

| Column | Type | Description |
| :--- | :--- | :--- |
| `key` | `TEXT` | Primary Key. Configuration key. |
| `value` | `JSONB` | Configuration value. |

## 3. Audit Tables

### `uploads`
Immutable audit log of all upload attempts (successful or failed).

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` | Primary Key. |
| `attempt_at` | `TIMESTAMPTZ` | Time of the upload attempt. |
| `filename` | `TEXT` | Name of the file. |
| `size` | `BIGINT` | Bytes transferred. |
| `success` | `BOOLEAN` | Outcome of the attempt. |
| `error_message` | `TEXT` | Error details if failed. |

## 4. TimescaleDB Configuration

- **Chunk Time Interval**: 24 hours (for `recordings`, `detections`, `weather`).
- **Retention Policy**: Managed by `Janitor` service (default: 30 days for local recordings).
