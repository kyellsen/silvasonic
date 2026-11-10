-- Silvasonic station schema (SQLite, ADR-0037), names per ADR-0033.
-- Schema version 1.
--
-- Applied by silvasonic.core.database.schema when a connection finds
-- PRAGMA user_version = 0. The ORM models in silvasonic.core.database.models
-- mirror these tables.
--
-- Conventions:
--   * Every table is STRICT: SQLite rejects a value of the wrong type.
--   * An identifier of a row created at runtime is a UUIDv7, stored as 32
--     lower-case hex digits (SQLAlchemy's Uuid type on SQLite). The ORM
--     generates it (silvasonic.core.ids.uuid7); the column DEFAULT builds an
--     equivalent one (millisecond timestamp, version 7, variant 10xx, random
--     rest) for raw SQL that leaves it out.
--   * A point in time is INTEGER microseconds since the Unix epoch, UTC
--     (silvasonic.core.database.types.UTCDateTime).
--   * A boolean is INTEGER 0 or 1.
--   * A JSON document is TEXT that must be valid JSON.

CREATE TABLE microphone_profiles (
    slug TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    config TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(config)),
    built_in INTEGER NOT NULL DEFAULT 0 CHECK (built_in IN (0, 1))
) STRICT;

CREATE TABLE microphones (
    id TEXT NOT NULL PRIMARY KEY DEFAULT (lower(
        printf('%012x', CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER))
        || '7' || substr(hex(randomblob(2)), 2, 3)
        || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2, 3)
        || hex(randomblob(6))
    )),
    hardware_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    serial_number TEXT NOT NULL UNIQUE,
    model TEXT NOT NULL,
    connection_state TEXT NOT NULL DEFAULT 'disconnected',
    enrollment_state TEXT NOT NULL DEFAULT 'pending',
    first_seen_at INTEGER,
    last_seen_at INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    profile_slug TEXT REFERENCES microphone_profiles (slug),
    hardware TEXT NOT NULL CHECK (json_valid(hardware)),
    workspace_name TEXT UNIQUE
) STRICT;

CREATE TABLE settings (
    section TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL CHECK (json_valid(value)),
    -- Optimistic concurrency for the API's If-Match (ADR-0033); every update bumps it
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER))
) STRICT;

CREATE TRIGGER settings_revision AFTER UPDATE ON settings
-- Every update ends at OLD + 1, also one that set revision itself (as in ADR-0033).
FOR EACH ROW WHEN NEW.revision IS NOT OLD.revision + 1
BEGIN
    UPDATE settings SET revision = OLD.revision + 1 WHERE section = NEW.section;
END;

CREATE TABLE modules (
    id TEXT NOT NULL PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    updated_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER))
) STRICT;

CREATE TABLE users (
    id TEXT NOT NULL PRIMARY KEY DEFAULT (lower(
        printf('%012x', CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER))
        || '7' || substr(hex(randomblob(2)), 2, 3)
        || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2, 3)
        || hex(randomblob(6))
    )),
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER)),
    updated_at INTEGER NOT NULL
        DEFAULT (CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER))
) STRICT;

CREATE TABLE species (
    id TEXT NOT NULL PRIMARY KEY,
    analyzer TEXT NOT NULL,
    label TEXT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_names TEXT NOT NULL CHECK (json_valid(common_names)),
    descriptions TEXT NOT NULL CHECK (json_valid(descriptions)),
    category TEXT NOT NULL DEFAULT 'other',
    watched INTEGER NOT NULL DEFAULT 0 CHECK (watched IN (0, 1)),
    image_path TEXT,
    image_source TEXT,
    conservation_status TEXT,
    UNIQUE (analyzer, label)
) STRICT;

CREATE TABLE weather_observations (
    observed_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    station_code TEXT,
    temperature_c REAL,
    humidity_percent REAL,
    pressure_hpa REAL,
    wind_speed_kmh REAL,
    wind_gusts_kmh REAL,
    precipitation_mm REAL,
    cloud_cover_percent INTEGER,
    uv_index REAL,
    sunshine_duration_s REAL,
    weather_code INTEGER,
    forecast INTEGER NOT NULL DEFAULT 0 CHECK (forecast IN (0, 1)),
    extra TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extra)),
    PRIMARY KEY (observed_at, source)
) STRICT;

CREATE TABLE recordings (
    id TEXT NOT NULL PRIMARY KEY DEFAULT (lower(
        printf('%012x', CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER))
        || '7' || substr(hex(randomblob(2)), 2, 3)
        || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2, 3)
        || hex(randomblob(6))
    )),
    started_at INTEGER NOT NULL,
    microphone_id TEXT NOT NULL REFERENCES microphones (id),
    raw_path TEXT NOT NULL,
    processed_path TEXT,
    duration_s REAL NOT NULL,
    sample_rate_hz INTEGER NOT NULL,
    channels INTEGER NOT NULL DEFAULT 1,
    raw_size_bytes INTEGER NOT NULL,
    processed_size_bytes INTEGER NOT NULL DEFAULT 0,
    uploaded_at INTEGER,
    -- Soft delete: set when the local audio is removed (retention | missing)
    deleted_at INTEGER,
    deletion_reason TEXT,
    -- Worker Pull state per analyzer (ADR-0018, silvasonic.core.schemas.analysis)
    analysis_state TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(analysis_state)),
    -- 0: named while the system clock was unsynchronised (Issue 002)
    clock_synced INTEGER NOT NULL DEFAULT 1 CHECK (clock_synced IN (0, 1))
) STRICT;

CREATE INDEX ix_recordings_started_at ON recordings (started_at);
CREATE INDEX ix_recordings_microphone_id ON recordings (microphone_id);
CREATE INDEX ix_recordings_raw_path ON recordings (raw_path);
CREATE INDEX ix_recordings_processed_path ON recordings (processed_path);
-- Worker Pull: oldest recordings still on disk
CREATE INDEX ix_recordings_analysis_pending ON recordings (started_at) WHERE deleted_at IS NULL;
-- Upload Worker: oldest recordings not yet uploaded
CREATE INDEX ix_recordings_upload_pending ON recordings (started_at)
    WHERE uploaded_at IS NULL AND deleted_at IS NULL;

CREATE TABLE detections (
    id TEXT NOT NULL PRIMARY KEY DEFAULT (lower(
        printf('%012x', CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER))
        || '7' || substr(hex(randomblob(2)), 2, 3)
        || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2, 3)
        || hex(randomblob(6))
    )),
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL,
    recording_id TEXT NOT NULL REFERENCES recordings (id),
    analyzer TEXT NOT NULL,
    confidence REAL NOT NULL,
    label TEXT NOT NULL,
    species_id TEXT REFERENCES species (id),
    clip_path TEXT,
    details TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details)),
    -- Review of the detection: unreviewed, confirmed, rejected
    review_state TEXT NOT NULL DEFAULT 'unreviewed',
    corrected_species_id TEXT REFERENCES species (id),
    review_note TEXT,
    reviewed_at INTEGER,
    reviewed_by TEXT REFERENCES users (id)
) STRICT;

CREATE INDEX ix_detections_started_at ON detections (started_at);
CREATE INDEX ix_detections_label ON detections (label);
CREATE INDEX ix_detections_species_id ON detections (species_id);
CREATE INDEX ix_detections_recording_id ON detections (recording_id);
CREATE INDEX ix_detections_analyzer ON detections (analyzer);

CREATE TABLE uploads (
    id TEXT NOT NULL PRIMARY KEY DEFAULT (lower(
        printf('%012x', CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER))
        || '7' || substr(hex(randomblob(2)), 2, 3)
        || substr('89ab', 1 + abs(random()) % 4, 1) || substr(hex(randomblob(2)), 2, 3)
        || hex(randomblob(6))
    )),
    recording_id TEXT NOT NULL REFERENCES recordings (id),
    attempted_at INTEGER NOT NULL,
    filename TEXT NOT NULL,
    remote_path TEXT,
    size_bytes INTEGER NOT NULL,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_message TEXT
) STRICT;

CREATE INDEX ix_uploads_recording_id ON uploads (recording_id);
CREATE INDEX ix_uploads_attempted_at ON uploads (attempted_at DESC);
