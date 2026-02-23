"""Mock data for the Silvasonic Web Mock service.

All data is hardcoded Python — no database or Redis required.
When real routes are implemented, replace the imports in ``__main__.py``
route-by-route with real async queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Station identity
# ---------------------------------------------------------------------------

STATION = {
    "name": "Silvasonic-01",
    "location": "Teststandort Wald",
    "version": "0.2.0-mock",
}

# ---------------------------------------------------------------------------
# System health / dashboard metrics
# ---------------------------------------------------------------------------

SYSTEM_METRICS = {
    "nvme_used_pct": 68,
    "nvme_used_gb": 136,
    "nvme_total_gb": 200,
    "cpu_temp_c": 51,
    "cpu_load_pct": 12,
    "ram_used_mb": 842,
    "ram_total_mb": 4096,
    "uptime_h": 47,
    "alert_count": 2,
    "last_event": "2026-02-23T17:43:15Z",
}

ACTIVE_RECORDERS = 2
ACTIVE_UPLOADERS = 1

ALERTS = [
    {"level": "warn", "message": "Dropped frames detected on mic_01 (3 frames)", "ts": "17:43:15"},
    {"level": "warn", "message": "NVMe usage above 65 % threshold", "ts": "17:30:00"},
]

# ---------------------------------------------------------------------------
# Recorders (max 5, using Bento-Grid layout)
# ---------------------------------------------------------------------------


@dataclass
class RecorderMock:
    """Mock recorder instance data."""

    id: str
    label: str
    device: str
    status: str  # "recording" | "idle" | "error"
    sample_rate: int  # Hz
    channels: int
    segment_s: int  # seconds
    gain_db: float
    level_pct: int  # 0-100 simulated live level
    last_segment: str


RECORDERS: list[RecorderMock] = [
    RecorderMock(
        id="mic_01",
        label="Ultramic-01",
        device="/dev/snd/pcmC1D0c",
        status="recording",
        sample_rate=192_000,
        channels=1,
        segment_s=300,
        gain_db=12.0,
        level_pct=72,
        last_segment="2026-02-23T17:43:00Z",
    ),
    RecorderMock(
        id="mic_02",
        label="Ultramic-02",
        device="/dev/snd/pcmC2D0c",
        status="recording",
        sample_rate=96_000,
        channels=1,
        segment_s=300,
        gain_db=6.0,
        level_pct=45,
        last_segment="2026-02-23T17:43:05Z",
    ),
]

# ---------------------------------------------------------------------------
# Uploaders (max 3, using Bento-Grid layout)
# ---------------------------------------------------------------------------


@dataclass
class UploaderMock:
    """Mock uploader instance data."""

    id: str
    label: str
    target_type: str  # "nextcloud" | "rclone-s3" | ...
    status: str  # "syncing" | "idle" | "throttled" | "error"
    queue_files: int
    throughput_kbps: int
    last_sync: str
    schedule: str


UPLOADERS: list[UploaderMock] = [
    UploaderMock(
        id="upload_01",
        label="Nextcloud-Backup",
        target_type="nextcloud",
        status="syncing",
        queue_files=14,
        throughput_kbps=320,
        last_sync="2026-02-23T17:45:00Z",
        schedule="*/5 * * * *",
    ),
]

# ---------------------------------------------------------------------------
# Bird detections (BirdNET)
# ---------------------------------------------------------------------------


@dataclass
class BirdDetection:
    """Single BirdNET detection event."""

    id: int
    species_en: str
    species_de: str
    species_sci: str
    confidence: float  # 0.0-1.0
    recording_file: str
    ts: str
    duration_s: float
    mic: str


BIRD_DETECTIONS: list[BirdDetection] = [
    BirdDetection(
        1,
        "Common Blackbird",
        "Amsel",
        "Turdus merula",
        0.97,
        "rec_001.wav",
        "2026-02-23T03:15:42Z",
        4.2,
        "mic_01",
    ),
    BirdDetection(
        2,
        "Great Tit",
        "Kohlmeise",
        "Parus major",
        0.91,
        "rec_001.wav",
        "2026-02-23T03:16:05Z",
        2.8,
        "mic_01",
    ),
    BirdDetection(
        3,
        "European Robin",
        "Rotkehlchen",
        "Erithacus rubecula",
        0.88,
        "rec_002.wav",
        "2026-02-23T04:02:11Z",
        3.5,
        "mic_02",
    ),
    BirdDetection(
        4,
        "Common Chaffinch",
        "Buchfink",
        "Fringilla coelebs",
        0.79,
        "rec_003.wav",
        "2026-02-23T05:30:00Z",
        2.1,
        "mic_01",
    ),
    BirdDetection(
        5,
        "Eurasian Nuthatch",
        "Kleiber",
        "Sitta europaea",
        0.74,
        "rec_003.wav",
        "2026-02-23T05:30:45Z",
        3.0,
        "mic_02",
    ),
]

BIRD_SPECIES_SUMMARY: list[dict[str, Any]] = [
    {
        "species_en": "Common Blackbird",
        "species_de": "Amsel",
        "count": 42,
        "last_seen": "2026-02-23T17:10:00Z",
    },
    {
        "species_en": "Great Tit",
        "species_de": "Kohlmeise",
        "count": 28,
        "last_seen": "2026-02-23T16:50:00Z",
    },
    {
        "species_en": "European Robin",
        "species_de": "Rotkehlchen",
        "count": 19,
        "last_seen": "2026-02-23T14:22:00Z",
    },
]

# ---------------------------------------------------------------------------
# Bat detections (BatDetect) — minimal placeholder
# ---------------------------------------------------------------------------

BAT_SPECIES_SUMMARY: list[dict[str, Any]] = [
    {
        "species_en": "Common Pipistrelle",
        "species_de": "Zwergfledermaus",
        "count": 87,
        "last_seen": "2026-02-23T23:45:00Z",
    },
    {
        "species_en": "Soprano Pipistrelle",
        "species_de": "Mückenfledermaus",
        "count": 31,
        "last_seen": "2026-02-23T22:30:00Z",
    },
]

# ---------------------------------------------------------------------------
# Settings (placeholder values)
# ---------------------------------------------------------------------------

SETTINGS: dict[str, Any] = {
    "station_name": STATION["name"],
    "timezone": "Europe/Berlin",
    "language": "de",
    "birdnet_enabled": True,
    "batdetect_enabled": True,
    "weather_enabled": False,
    "recording_policy": {
        "max_segment_s": 300,
        "min_free_gb": 20,
        "delete_after_upload": False,
    },
}

# ---------------------------------------------------------------------------
# Fake log lines (for SSE console stream)
# ---------------------------------------------------------------------------

FAKE_LOG_LINES: list[str] = [
    '{"level":"info","service":"recorder","instance_id":"mic_01","message":"segment written: rec_001.wav","timestamp":"2026-02-23T17:43:00Z"}',  # noqa: E501
    '{"level":"warn","service":"recorder","instance_id":"mic_01","message":"dropped frames: 3","timestamp":"2026-02-23T17:43:15Z"}',  # noqa: E501
    '{"level":"info","service":"birdnet","instance_id":"birdnet","message":"Analysis complete: 5 detections in rec_001.wav","timestamp":"2026-02-23T17:44:00Z"}',  # noqa: E501
    '{"level":"info","service":"uploader","instance_id":"upload_01","message":"Uploaded rec_001.wav (4.2 MB) -> Nextcloud","timestamp":"2026-02-23T17:44:30Z"}',  # noqa: E501
    '{"level":"info","service":"controller","instance_id":"controller","message":"Heartbeat OK - 2 recorders active","timestamp":"2026-02-23T17:45:00Z"}',  # noqa: E501
    '{"level":"info","service":"recorder","instance_id":"mic_02","message":"segment written: rec_002.wav","timestamp":"2026-02-23T17:48:00Z"}',  # noqa: E501
    '{"level":"info","service":"birdnet","instance_id":"birdnet","message":"Analysis complete: 3 detections in rec_002.wav","timestamp":"2026-02-23T17:49:00Z"}',  # noqa: E501
]

LOG_SERVICES: list[dict[str, str]] = [
    {"id": "controller", "label": "Controller"},
    {"id": "mic_01", "label": "Recorder mic_01"},
    {"id": "mic_02", "label": "Recorder mic_02"},
    {"id": "birdnet", "label": "BirdNET"},
    {"id": "upload_01", "label": "Uploader"},
]
