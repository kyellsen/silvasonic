-- Silvasonic station schema (SQLite, ADR-0037). Schema version 1.
--
-- Applied by silvasonic.core.database.schema when a connection finds
-- PRAGMA user_version = 0. The ORM models in silvasonic.core.database.models
-- mirror these tables.
--
-- Conventions:
--   * Every table is STRICT: SQLite rejects a value of the wrong type.
--   * A point in time is INTEGER microseconds since the Unix epoch, UTC
--     (silvasonic.core.database.types.UTCDateTime).
--   * A boolean is INTEGER 0 or 1.
--   * A JSON document is TEXT that must be valid JSON.

CREATE TABLE microphone_profiles (
    slug TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    match_pattern TEXT,
    config TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config)),
    is_system INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1))
) STRICT;

CREATE TABLE devices (
    name TEXT NOT NULL PRIMARY KEY,
    serial_number TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offline',
    enrollment_status TEXT NOT NULL DEFAULT 'pending',
    last_seen INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    profile_slug TEXT REFERENCES microphone_profiles (slug),
    config TEXT NOT NULL CHECK (json_valid(config)),
    workspace_name TEXT UNIQUE
) STRICT;

CREATE TABLE system_config (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL CHECK (json_valid(value)),
    updated_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER))
) STRICT;

CREATE TABLE managed_services (
    name TEXT NOT NULL PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    updated_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER))
) STRICT;

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER)),
    updated_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER))
) STRICT;

CREATE TABLE taxonomy (
    worker TEXT NOT NULL,
    label TEXT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_names TEXT NOT NULL CHECK (json_valid(common_names)),
    description TEXT NOT NULL CHECK (json_valid(description)),
    image_path TEXT,
    image_source TEXT,
    conservation_status TEXT,
    PRIMARY KEY (worker, label)
) STRICT;

CREATE TABLE weather (
    time INTEGER NOT NULL,
    source TEXT NOT NULL,
    station_code TEXT,
    temp_c REAL,
    humidity REAL,
    pressure_hpa REAL,
    wind_speed_kmh REAL,
    wind_gusts_kmh REAL,
    precipitation_mm REAL,
    cloud_cover INTEGER,
    uv_index REAL,
    sunshine_duration REAL,
    weather_code INTEGER,
    is_forecast INTEGER NOT NULL DEFAULT 0 CHECK (is_forecast IN (0, 1)),
    extra TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extra)),
    PRIMARY KEY (time, source)
) STRICT;

CREATE TABLE recordings (
    id INTEGER PRIMARY KEY,
    time INTEGER NOT NULL,
    sensor_id TEXT NOT NULL REFERENCES devices (name),
    file_raw TEXT NOT NULL,
    file_processed TEXT,
    duration REAL NOT NULL,
    sample_rate INTEGER NOT NULL,
    filesize_raw INTEGER NOT NULL,
    filesize_processed INTEGER NOT NULL DEFAULT 0,
    uploaded INTEGER NOT NULL DEFAULT 0 CHECK (uploaded IN (0, 1)),
    uploaded_at INTEGER,
    local_deleted INTEGER NOT NULL DEFAULT 0 CHECK (local_deleted IN (0, 1)),
    -- Worker Pull state per analyzer (ADR-0018), e.g. {"birdnet": "done"}
    analysis_state TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(analysis_state)),
    -- Named while the system clock was unsynchronised: time may be off (Issue 002)
    clock_unsynced INTEGER NOT NULL DEFAULT 0 CHECK (clock_unsynced IN (0, 1))
) STRICT;

CREATE INDEX ix_recordings_time ON recordings (time);
CREATE INDEX ix_recordings_sensor_id ON recordings (sensor_id);
CREATE INDEX ix_recordings_file_raw ON recordings (file_raw);
CREATE INDEX ix_recordings_file_processed ON recordings (file_processed);
-- Worker Pull: oldest recordings still on disk
CREATE INDEX ix_recordings_analysis_pending ON recordings (time) WHERE local_deleted = 0;
-- Upload Worker: oldest recordings not yet uploaded
CREATE INDEX ix_recordings_upload_pending ON recordings (time)
    WHERE uploaded = 0 AND local_deleted = 0;

CREATE TABLE detections (
    id INTEGER PRIMARY KEY,
    time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    recording_id INTEGER NOT NULL REFERENCES recordings (id),
    worker TEXT NOT NULL,
    confidence REAL NOT NULL,
    label TEXT NOT NULL,
    common_name TEXT,
    clip_path TEXT,
    details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details))
) STRICT;

CREATE INDEX ix_detections_time ON detections (time);
CREATE INDEX ix_detections_label ON detections (label);
CREATE INDEX ix_detections_recording_id ON detections (recording_id);
CREATE INDEX ix_detections_worker ON detections (worker);

CREATE TABLE uploads (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings (id),
    attempt_at INTEGER NOT NULL,
    filename TEXT NOT NULL,
    remote_path TEXT,
    size INTEGER NOT NULL,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_message TEXT
) STRICT;

CREATE INDEX ix_uploads_recording_id ON uploads (recording_id);
CREATE INDEX ix_uploads_attempt_at ON uploads (attempt_at DESC);
