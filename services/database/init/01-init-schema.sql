-- Silvasonic Initial Schema (Consolidated, pls modifiy directly services/database/init/01-init-schema.sql, do use extra files for migrations)
-- Replaces Alembic Migrations: 833e0e6f1e08, 20260202_varchar_text
-- Naming and identifiers: ADR-0033 (one name per concept, UUIDv7 for runtime rows)

-- 0. UUIDv7 (RFC 9562)
-- 48-bit Unix milliseconds, version 7, variant 10, 74 random bits.
-- PostgreSQL 18 ships uuidv7() in pg_catalog, which is searched first; this
-- polyfill becomes dead code once the image moves to PostgreSQL 18.
-- gen_random_uuid() (built in since PostgreSQL 13) supplies the random bits and
-- the variant; bits 52 and 53 turn its version nibble 0100 (v4) into 0111 (v7).
CREATE OR REPLACE FUNCTION uuidv7() RETURNS uuid AS $$
    SELECT encode(
        set_bit(
            set_bit(
                overlay(
                    uuid_send(gen_random_uuid())
                    PLACING substring(
                        int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint)
                        FROM 3
                    )
                    FROM 1 FOR 6
                ),
                52, 1
            ),
            53, 1
        ),
        'hex'
    )::uuid;
$$ LANGUAGE sql VOLATILE;

-- 1. Microphone Profiles
CREATE TABLE microphone_profiles (
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    built_in BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (slug)
);

-- 2. Microphones
-- hardware_id is the Stable Device ID derived from USB vendor, product and serial
-- (or the USB port); name is the label the user chooses, the model until then.
CREATE TABLE microphones (
    id UUID NOT NULL DEFAULT uuidv7(),
    hardware_id TEXT NOT NULL,
    name TEXT NOT NULL,
    serial_number TEXT NOT NULL,
    model TEXT NOT NULL,
    connection_state TEXT NOT NULL DEFAULT 'disconnected',
    enrollment_state TEXT NOT NULL DEFAULT 'pending',
    first_seen_at TIMESTAMP WITH TIME ZONE,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    profile_slug TEXT,
    hardware JSONB NOT NULL,
    workspace_name TEXT,
    PRIMARY KEY (id),
    UNIQUE (hardware_id),
    UNIQUE (serial_number),
    UNIQUE (workspace_name),
    FOREIGN KEY(profile_slug) REFERENCES microphone_profiles (slug)
);

-- 3. Settings (ADR-0023: Configuration Management)
-- One row per section; revision starts at 1 and grows with every write.
CREATE TABLE settings (
    section TEXT NOT NULL,
    value JSONB NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (section)
);

CREATE OR REPLACE FUNCTION settings_bump_revision() RETURNS trigger AS $$
BEGIN
    NEW.revision := OLD.revision + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER settings_revision
BEFORE UPDATE ON settings
FOR EACH ROW EXECUTE FUNCTION settings_bump_revision();

-- 4. Modules (ADR-0029: Tier-2 Lifecycle Orchestration)
-- One switch per optional feature, whichever process implements it.
-- Domain/business settings remain in settings (ADR-0023).
CREATE TABLE modules (
    id TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id)
);

-- 5. Users (ADR-0023: Authentication)
CREATE TABLE users (
    id UUID NOT NULL DEFAULT uuidv7(),
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE (username)
);

-- 6. Species
-- id is a slug of the scientific name; (analyzer, label) is how an analyzer names it.
CREATE TABLE species (
    id TEXT NOT NULL,
    analyzer TEXT NOT NULL,
    label TEXT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_names JSONB NOT NULL,
    descriptions JSONB NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    watched BOOLEAN NOT NULL DEFAULT FALSE,
    image_path TEXT,
    image_source TEXT,
    conservation_status TEXT,
    PRIMARY KEY (id),
    UNIQUE (analyzer, label)
);

-- 7. Weather Observations (Hypertable)
CREATE TABLE weather_observations (
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source TEXT NOT NULL,
    station_code TEXT,
    temperature_c DOUBLE PRECISION,
    humidity_percent DOUBLE PRECISION,
    pressure_hpa DOUBLE PRECISION,
    wind_speed_kmh DOUBLE PRECISION,
    wind_gusts_kmh DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    cloud_cover_percent INTEGER,
    uv_index DOUBLE PRECISION,
    sunshine_duration_s DOUBLE PRECISION,
    weather_code INTEGER,
    forecast BOOLEAN NOT NULL,
    extra JSONB NOT NULL,
    PRIMARY KEY (observed_at, source)
);

-- 8. Recordings (Standard Table — ADR-0025: No Hypertable)
-- Kept as standard table to preserve FK constraints from detections and uploads.
-- Data volume (~2M rows/year) does not require partitioning. See ADR-0025.
CREATE TABLE recordings (
    id UUID NOT NULL DEFAULT uuidv7(),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    microphone_id UUID NOT NULL,
    raw_path TEXT NOT NULL,
    processed_path TEXT,
    duration_s DOUBLE PRECISION NOT NULL,
    -- Native rate of the microphone (the raw stream), not of the indexed file
    sample_rate_hz INTEGER NOT NULL,
    channels INTEGER NOT NULL DEFAULT 1,
    raw_size_bytes BIGINT NOT NULL,
    processed_size_bytes BIGINT NOT NULL DEFAULT 0,
    uploaded_at TIMESTAMP WITH TIME ZONE,
    -- Set when the local audio is removed; deletion_reason: retention | missing
    deleted_at TIMESTAMP WITH TIME ZONE,
    deletion_reason TEXT,
    -- {"<analyzer>": {"state", "reason", "finished_at", "detection_count"}}
    analysis_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- FALSE: named while the system clock was unsynchronised, `started_at` may be off (Issue 002)
    clock_synced BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    FOREIGN KEY(microphone_id) REFERENCES microphones (id)
);
CREATE INDEX ix_recordings_started_at ON recordings (started_at);
CREATE INDEX ix_recordings_microphone_id ON recordings (microphone_id);
-- Indexer existence checks look recordings up by file path
CREATE INDEX ix_recordings_raw_path ON recordings (raw_path);
CREATE INDEX ix_recordings_processed_path ON recordings (processed_path);

-- Worker Pull (ADR-0018): Analysis workers claim unprocessed recordings.
-- Covers queries filtering on deleted_at, replacing a standalone deletion index.
CREATE INDEX ix_recordings_analysis_pending
ON recordings (started_at ASC)
WHERE deleted_at IS NULL;

-- Upload polling (v0.6.0): Cloud-Sync-Worker finds un-uploaded, non-deleted recordings.
CREATE INDEX ix_recordings_upload_pending
ON recordings (started_at ASC)
WHERE uploaded_at IS NULL AND deleted_at IS NULL;

-- 9. Detections (Hypertable)
-- TimescaleDB needs the partition column in the primary key; ix_detections_id
-- lets a detection be addressed by id alone.
CREATE TABLE detections (
    id UUID NOT NULL DEFAULT uuidv7(),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE NOT NULL,
    recording_id UUID NOT NULL,
    analyzer TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    -- The label as the analyzer reported it; species_id is what it means
    label TEXT NOT NULL,
    species_id TEXT,
    clip_path TEXT,
    details JSONB NOT NULL,
    review_state TEXT NOT NULL DEFAULT 'unreviewed',
    corrected_species_id TEXT,
    review_note TEXT,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by UUID,
    PRIMARY KEY (started_at, id),
    FOREIGN KEY(recording_id) REFERENCES recordings (id),
    FOREIGN KEY(species_id) REFERENCES species (id),
    FOREIGN KEY(corrected_species_id) REFERENCES species (id),
    FOREIGN KEY(reviewed_by) REFERENCES users (id)
);
CREATE INDEX ix_detections_id ON detections (id);
CREATE INDEX ix_detections_started_at ON detections (started_at);
CREATE INDEX ix_detections_label ON detections (label);
CREATE INDEX ix_detections_species_id ON detections (species_id);
CREATE INDEX ix_detections_recording_id ON detections (recording_id);
CREATE INDEX ix_detections_analyzer ON detections (analyzer);

-- 10. Uploads
CREATE TABLE uploads (
    id UUID NOT NULL DEFAULT uuidv7(),
    recording_id UUID NOT NULL,
    attempted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    filename TEXT NOT NULL,
    remote_path TEXT,
    size_bytes BIGINT NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    PRIMARY KEY (id),
    FOREIGN KEY(recording_id) REFERENCES recordings (id)
);
CREATE INDEX ix_uploads_recording_id ON uploads (recording_id);
CREATE INDEX ix_uploads_attempted_at ON uploads (attempted_at DESC);

-- 11. TimescaleDB Setup
SELECT create_hypertable('weather_observations', 'observed_at', if_not_exists => TRUE);
SELECT create_hypertable('detections', 'started_at', if_not_exists => TRUE);
