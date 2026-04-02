"""Mock data for the Silvasonic Web Mock service.

All data is hardcoded Python — no database or Redis required.
When real routes are implemented, replace the imports in ``__main__.py``
route-by-route with real async queries.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from silvasonic.core import __version__

# ---------------------------------------------------------------------------
# Station identity
# ---------------------------------------------------------------------------

STATION = {
    "name": "Silvasonic-001",
    "location": "Test Location Forest",
    "version": f"{__version__}-mock",
}

# ---------------------------------------------------------------------------
# System health / dashboard metrics
# ---------------------------------------------------------------------------

SYSTEM_METRICS = {
    "nvme_used_pct": 68,
    "nvme_used_gb": 136,
    "nvme_total_gb": 200,
    "cpu_temp_c": 51,
    "cpu_load_pct": 52,
    "cpu_cores_load_pct": [12, 94, 28, 74],
    "ram_used_mb": 842,
    "ram_total_mb": 4096,
    "uptime_h": 47,
    "alert_count": 2,
    "last_event": "2026-02-23T17:43:15Z",
}

ACTIVE_RECORDERS = 3
UPLOAD_ENABLED = True

ALERTS = [
    {"level": "warn", "message": "Dropped frames detected on mic_01 (3 frames)", "ts": "17:43:15"},
    {"level": "warn", "message": "NVMe usage above 65 % threshold", "ts": "17:30:00"},
]

# ---------------------------------------------------------------------------
# Weather Mock Data
# ---------------------------------------------------------------------------


def _generate_weather_statistics(days: int = 30) -> dict[str, list[Any]]:
    now = datetime(2026, 2, 24, 0, 0, 0)
    start = now - timedelta(days=days)

    timestamps = []
    temperature = []
    temperature_24h = []
    precipitation = []
    humidity = []
    pressure = []
    wind = []
    wind_gust = []
    sunshine = []

    current_time = start
    total_intervals = days * 24 * 6

    for i in range(total_intervals):
        timestamps.append(current_time.strftime("%Y-%m-%d %H:%M"))

        hour_offset = current_time.hour + current_time.minute / 60.0
        diurnal = math.sin((hour_offset - 9) * math.pi / 12)
        day_index = i / (24 * 6)
        seasonal = math.sin(day_index * math.pi / 15) * 5

        noise_temp = random.uniform(-0.6, 0.6)
        temp_val = 8.0 + diurnal * 4.0 + seasonal + noise_temp + math.sin(i / 20.0) * 0.5
        temperature.append(float(f"{temp_val:.1f}"))

        noise_temp24 = random.uniform(-0.1, 0.1)
        temp_24h = 8.0 + seasonal + noise_temp24
        temperature_24h.append(float(f"{temp_24h:.1f}"))

        precip = 0.0
        if (i % 144 == 0) or (i % 200 == 0):
            precip_val = random.uniform(2.0, 5.0)
            precip = float(f"{precip_val:.1f}")
        elif (i % 144 == 1) or (i % 200 == 1):
            precip_val = random.uniform(0.5, 2.0)
            precip = float(f"{precip_val:.1f}")
        elif random.random() < 0.015:  # 1.5% chance for random rain
            precip_val = random.uniform(0.1, 1.5)
            precip = float(f"{precip_val:.1f}")
        precipitation.append(precip)

        noise_hum = random.uniform(-4.0, 4.0)
        hum_val = max(
            30.0, min(100.0, 75.0 - diurnal * 15.0 + noise_hum + math.cos(i / 30.0) * 5.0)
        )
        if precip > 0:
            hum_val = min(100.0, hum_val + random.uniform(5.0, 15.0))
        humidity.append(float(f"{hum_val:.1f}"))

        noise_pres = random.uniform(-1.0, 1.0)
        pres_val = 1013.0 + seasonal * 2.0 + noise_pres + math.cos(i / 100.0) * 5.0
        pressure.append(float(f"{pres_val:.1f}"))

        noise_wind = random.uniform(-0.5, 1.5)
        w_val = max(0.0, 2.5 + diurnal * 1.5 + noise_wind + math.sin(i / 50.0) * 1.5)
        wind.append(float(f"{w_val:.1f}"))

        noise_gust = random.uniform(1.0, 4.0)
        wg_val = w_val + noise_gust + (precip * 0.8)
        wind_gust.append(float(f"{wg_val:.1f}"))

        sun = 0
        if 6 <= current_time.hour <= 18:
            noise_sun = random.uniform(-2.0, 2.0)
            sun_val = 5.0 + diurnal * 5.0 - (precip * 5.0) + noise_sun
            sun = max(0, min(10, round(sun_val)))
        sunshine.append(sun)

        current_time += timedelta(minutes=10)

    return {
        "timestamps": timestamps,
        "temperature": temperature,
        "temperature_24h": temperature_24h,
        "precipitation": precipitation,
        "humidity": humidity,
        "pressure": pressure,
        "wind": wind,
        "wind_gust": wind_gust,
        "sunshine": sunshine,
    }


WEATHER_STATISTICS = _generate_weather_statistics()

# ---------------------------------------------------------------------------
# Services Inspector
# ---------------------------------------------------------------------------


@dataclass
class ServiceMock:
    """Mock service instance for dashboard inspector."""

    id: str
    name: str
    status: str  # "running" | "down"
    task: str


INSPECTOR_SERVICES: list[ServiceMock] = [
    ServiceMock("controller", "Controller", "running", "Heartbeat OK"),
    ServiceMock("postgres", "PostgresDB", "running", "Idle"),
    ServiceMock("redis", "Redis", "running", "Active connections: 4"),
    ServiceMock("recorder", "Recorder", "down", "Offline"),
    ServiceMock("upload-worker", "Upload Worker", "running", "Uploading rec_001.wav"),
    ServiceMock("birdnet", "BirdNet", "down", "Offline"),
    ServiceMock("batdetect", "BatDetect", "running", "Idle"),
    ServiceMock("weather", "Weather", "running", "Fetching API..."),
    ServiceMock("webmock", "Web Mock", "running", "Serving UI"),
    ServiceMock("health", "HealthChecker", "running", "Checking services"),
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
    enrollment_status: str  # "enrolled" | "generic" | "pending"
    watchdog_restarts: int
    watchdog_max_restarts: int


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
        enrollment_status="enrolled",
        watchdog_restarts=0,
        watchdog_max_restarts=5,
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
        enrollment_status="generic",
        watchdog_restarts=2,
        watchdog_max_restarts=5,
    ),
    RecorderMock(
        id="mic_03",
        label="Audiomoth-01",
        device="/dev/snd/pcmC3D0c",
        status="idle",
        sample_rate=48_000,
        channels=1,
        segment_s=300,
        gain_db=24.0,
        level_pct=0,
        last_segment="2026-02-23T17:00:00Z",
        enrollment_status="pending",
        watchdog_restarts=0,
        watchdog_max_restarts=5,
    ),
]

# ---------------------------------------------------------------------------
# Upload Status (single target)
# ---------------------------------------------------------------------------


@dataclass
class UploadStatusMock:
    """Mock upload status instance data."""

    id: str
    label: str
    target_type: str  # "nextcloud" | "rclone-s3" | ...
    status: str  # "syncing" | "idle" | "throttled" | "error"
    queue_files: int
    throughput_kbps: int
    last_sync: str
    schedule: str
    bandwidth_limit_kbps: int | None  # None = unlimited
    upload_window: str  # "always" | "HH:MM-HH:MM"


UPLOAD_STATUS: UploadStatusMock = UploadStatusMock(
    id="upload_01",
    label="Nextcloud-Backup",
    target_type="nextcloud",
    status="syncing",
    queue_files=14,
    throughput_kbps=320,
    last_sync="2026-02-23T17:45:00Z",
    schedule="*/5 * * * *",
    bandwidth_limit_kbps=None,
    upload_window="always",
)

# ---------------------------------------------------------------------------
# Bird detections (BirdNET)
# ---------------------------------------------------------------------------


@dataclass
class BirdDetection:
    """Single BirdNET detection event."""

    id: int
    species_en: str
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
        "id": "turdus-merula",
        "species_en": "Common Blackbird",
        "species_sci": "Turdus merula",
        "count": 42,
        "max_confidence": 0.97,
        "first_seen": "2026-02-10T08:15:00Z",
        "last_seen": "2026-02-23T17:10:00Z",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Turdus_merula.jpg?width=320",
    },
    {
        "id": "parus-major",
        "species_en": "Great Tit",
        "species_sci": "Parus major",
        "count": 28,
        "max_confidence": 0.94,
        "first_seen": "2026-02-12T09:20:00Z",
        "last_seen": "2026-02-23T16:50:00Z",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Parus_major.jpg?width=320",
    },
    {
        "id": "erithacus-rubecula",
        "species_en": "European Robin",
        "species_sci": "Erithacus rubecula",
        "count": 19,
        "max_confidence": 0.88,
        "first_seen": "2026-02-15T07:45:00Z",
        "last_seen": "2026-02-23T14:22:00Z",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Erithacus_rubecula.jpg?width=320",
    },
]

BIRD_TOP_10: list[dict[str, Any]] = [
    {"species_en": "Common Blackbird", "count": 142},
    {"species_en": "Great Tit", "count": 118},
    {"species_en": "European Robin", "count": 95},
    {"species_en": "Common Chaffinch", "count": 84},
    {"species_en": "House Sparrow", "count": 76},
    {"species_en": "Eurasian Blue Tit", "count": 62},
    {"species_en": "Common Starling", "count": 51},
    {"species_en": "Eurasian Magpie", "count": 45},
    {"species_en": "Carrion Crow", "count": 38},
    {"species_en": "Eurasian Nuthatch", "count": 29},
]

BIRD_RAREST: dict[str, Any] = {
    "species_en": "Common Kingfisher",
    "species_sci": "Alcedo atthis",
    "count": 2,
    "last_seen": "2026-02-23T08:15:00Z",
}

# ---------------------------------------------------------------------------
# Bat detections (BatDetect)
# ---------------------------------------------------------------------------


@dataclass
class BatDetection:
    """Single BatDetect detection event."""

    id: int
    species_en: str
    species_sci: str
    confidence: float  # 0.0-1.0
    recording_file: str
    ts: str
    duration_s: float
    mic: str


BAT_DETECTIONS: list[BatDetection] = [
    BatDetection(
        1,
        "Common Pipistrelle",
        "Pipistrellus pipistrellus",
        0.95,
        "rec_004.wav",
        "2026-02-23T23:45:12Z",
        1.2,
        "mic_01",
    ),
    BatDetection(
        2,
        "Soprano Pipistrelle",
        "Pipistrellus pygmaeus",
        0.88,
        "rec_004.wav",
        "2026-02-23T23:46:05Z",
        0.8,
        "mic_01",
    ),
    BatDetection(
        3,
        "Daubenton's Bat",
        "Myotis daubentonii",
        0.91,
        "rec_005.wav",
        "2026-02-24T00:12:11Z",
        2.5,
        "mic_02",
    ),
    BatDetection(
        4,
        "Noctule",
        "Nyctalus noctula",
        0.82,
        "rec_006.wav",
        "2026-02-24T01:30:00Z",
        1.5,
        "mic_01",
    ),
    BatDetection(
        5,
        "Brown Long-eared Bat",
        "Plecotus auritus",
        0.76,
        "rec_006.wav",
        "2026-02-24T01:35:45Z",
        2.0,
        "mic_02",
    ),
]

BAT_SPECIES_SUMMARY: list[dict[str, Any]] = [
    {
        "id": "pipistrellus-pipistrellus",
        "species_en": "Common Pipistrelle",
        "species_sci": "Pipistrellus pipistrellus",
        "count": 87,
        "last_seen": "2026-02-23T23:45:00Z",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Pipistrellus_pipistrellus.jpg?width=320",
    },
    {
        "id": "pipistrellus-pygmaeus",
        "species_en": "Soprano Pipistrelle",
        "species_sci": "Pipistrellus pygmaeus",
        "count": 31,
        "last_seen": "2026-02-23T22:30:00Z",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Pipistrellus_pygmaeus.jpg?width=320",
    },
    {
        "id": "myotis-daubentonii",
        "species_en": "Daubenton's Bat",
        "species_sci": "Myotis daubentonii",
        "count": 14,
        "last_seen": "2026-02-24T00:12:00Z",
        "image_url": "https://commons.wikimedia.org/wiki/Special:FilePath/Myotis_daubentonii.jpg?width=320",
    },
]

BAT_TOP_10: list[dict[str, Any]] = [
    {"species_en": "Common Pipistrelle", "count": 187},
    {"species_en": "Soprano Pipistrelle", "count": 94},
    {"species_en": "Daubenton's Bat", "count": 42},
    {"species_en": "Noctule", "count": 38},
    {"species_en": "Brown Long-eared Bat", "count": 21},
    {"species_en": "Serotine Bat", "count": 15},
    {"species_en": "Natterer's Bat", "count": 11},
    {"species_en": "Whiskered Bat", "count": 8},
    {"species_en": "Brandt's Bat", "count": 5},
    {"species_en": "Lesser Horseshoe Bat", "count": 2},
]

BAT_RAREST: dict[str, Any] = {
    "species_en": "Barbastelle",
    "species_sci": "Barbastella barbastellus",
    "count": 1,
    "last_seen": "2026-02-20T03:15:00Z",
}

# ---------------------------------------------------------------------------
# Processor (Indexer and Retention)
# ---------------------------------------------------------------------------

PROCESSOR_INDEXER_FILES: list[dict[str, Any]] = [
    {
        "filename": "20260223_174000_mic01.wav",
        "recorder": "mic_01",
        "size_mb": 4.2,
        "indexed_at": "2026-02-23T17:41:12Z",
        "status": "success",
    },
    {
        "filename": "20260223_173500_mic02.wav",
        "recorder": "mic_02",
        "size_mb": 4.1,
        "indexed_at": "2026-02-23T17:36:05Z",
        "status": "success",
    },
    {
        "filename": "20260223_173500_mic01.wav",
        "recorder": "mic_01",
        "size_mb": 4.2,
        "indexed_at": "2026-02-23T17:35:58Z",
        "status": "success",
    },
    {
        "filename": "20260223_173000_mic01.wav",
        "recorder": "mic_01",
        "size_mb": 4.2,
        "indexed_at": "2026-02-23T17:31:10Z",
        "status": "success",
    },
    {
        "filename": "20260223_173000_mic02.wav",
        "recorder": "mic_02",
        "size_mb": 0.8,
        "indexed_at": "2026-02-23T17:30:45Z",
        "status": "warn_short",
    },
]

PROCESSOR_RETENTION_EVENTS: list[dict[str, Any]] = [
    {
        "filename": "20260115_040000_mic01.wav",
        "deleted_at": "2026-02-23T02:15:00Z",
        "size_mb": 4.2,
        "escalation": "Level 1 (Age > 30d)",
    },
    {
        "filename": "20260115_040500_mic01.wav",
        "deleted_at": "2026-02-23T02:15:02Z",
        "size_mb": 4.2,
        "escalation": "Level 1 (Age > 30d)",
    },
    {
        "filename": "20260115_041000_mic01.wav",
        "deleted_at": "2026-02-23T02:15:05Z",
        "size_mb": 4.2,
        "escalation": "Level 1 (Age > 30d)",
    },
    {
        "filename": "20260222_120000_mic02.wav",
        "deleted_at": "2026-02-22T23:50:00Z",
        "size_mb": 4.1,
        "escalation": "Level 3 (Capacity > 90%)",
    },
    {
        "filename": "20260222_120500_mic02.wav",
        "deleted_at": "2026-02-22T23:50:02Z",
        "size_mb": 4.1,
        "escalation": "Level 3 (Capacity > 90%)",
    },
]

# ---------------------------------------------------------------------------
# Settings (placeholder values)
# ---------------------------------------------------------------------------

SETTINGS: dict[str, Any] = {
    "station_name": STATION["name"],
    "timezone": "Europe/Berlin",
    "latitude": 52.5200,
    "longitude": 13.4050,
    "language": "de",
    "poweroff_on_low_battery": True,
    "livesound_enabled": True,
    "birdnet_enabled": True,
    "batdetect_enabled": True,
    "weather_enabled": False,
    "birdnet_min_confidence": 0.75,
    "birdnet_time_start": "",
    "birdnet_time_end": "",
    "batdetect_min_confidence": 0.70,
    "batdetect_time_start": "",
    "batdetect_time_end": "",
    "recording_policy": {
        "max_segment_s": 300,
        "min_free_gb": 20,
        "delete_after_upload": False,
    },
    "remote": {
        "id": "remote_01",
        "name": "Cloud Backup (Nextcloud)",
        "target_type": "nextcloud",
        "url": "https://cloud.example.org/remote.php/webdav/",
        "username": "station-01-sync",
        "bandwidth_limit_kbps": None,
        "upload_window_start": "",
        "upload_window_end": "",
    },
    "user": {
        "username": "admin",
    },
}

# ---------------------------------------------------------------------------
# Upload Audit Log (for cloud sync detail page)
# ---------------------------------------------------------------------------

UPLOAD_AUDIT_LOG: list[dict[str, Any]] = [
    {
        "filename": "20260223_174000_mic01.wav",
        "target": "Nextcloud-Backup",
        "status": "success",
        "size_mb": 4.2,
        "duration_s": 12,
        "ts": "2026-02-23T17:44:30Z",
        "error": None,
    },
    {
        "filename": "20260223_173500_mic01.wav",
        "target": "Nextcloud-Backup",
        "status": "success",
        "size_mb": 4.2,
        "duration_s": 11,
        "ts": "2026-02-23T17:39:15Z",
        "error": None,
    },
    {
        "filename": "20260223_173000_mic01.wav",
        "target": "Nextcloud-Backup",
        "status": "failed",
        "size_mb": 4.2,
        "duration_s": 45,
        "ts": "2026-02-23T17:35:00Z",
        "error": "HTTP 503 Service Unavailable",
    },
    {
        "filename": "20260223_173000_mic01.wav",
        "target": "Nextcloud-Backup",
        "status": "retrying",
        "size_mb": 4.2,
        "duration_s": 0,
        "ts": "2026-02-23T17:37:00Z",
        "error": "Retry 1/3 scheduled",
    },
    {
        "filename": "20260223_170000_mic02.wav",
        "target": "Nextcloud-Backup",
        "status": "success",
        "size_mb": 4.1,
        "duration_s": 18,
        "ts": "2026-02-23T16:05:00Z",
        "error": None,
    },
    {
        "filename": "20260223_173000_mic02.wav",
        "target": "Nextcloud-Backup",
        "status": "success",
        "size_mb": 0.8,
        "duration_s": 3,
        "ts": "2026-02-23T17:34:00Z",
        "error": None,
    },
]

# ---------------------------------------------------------------------------
# Fake log lines (for SSE console stream)
# ---------------------------------------------------------------------------

FAKE_LOG_LINES: list[str] = [
    '{"level":"info","service":"recorder","instance_id":"mic_01","message":"segment written: rec_001.wav","timestamp":"2026-02-23T17:43:00Z"}',  # noqa: E501
    '{"level":"warn","service":"recorder","instance_id":"mic_01","message":"dropped frames: 3","timestamp":"2026-02-23T17:43:15Z"}',  # noqa: E501
    '{"level":"info","service":"birdnet","instance_id":"birdnet","message":"Analysis complete: 5 detections in rec_001.wav","timestamp":"2026-02-23T17:44:00Z"}',  # noqa: E501
    '{"level":"info","service":"processor","instance_id":"upload_worker","message":"Uploaded rec_001.wav (4.2 MB) -> Nextcloud","timestamp":"2026-02-23T17:44:30Z"}',  # noqa: E501
    '{"level":"info","service":"controller","instance_id":"controller","message":"Heartbeat OK - 2 recorders active","timestamp":"2026-02-23T17:45:00Z"}',  # noqa: E501
    '{"level":"info","service":"recorder","instance_id":"mic_02","message":"segment written: rec_002.wav","timestamp":"2026-02-23T17:48:00Z"}',  # noqa: E501
    '{"level":"info","service":"birdnet","instance_id":"birdnet","message":"Analysis complete: 3 detections in rec_002.wav","timestamp":"2026-02-23T17:49:00Z"}',  # noqa: E501
]

LOG_SERVICES: list[dict[str, str]] = [
    {"id": "controller", "label": "Controller"},
    {"id": "mic_01", "label": "Recorder mic_01"},
    {"id": "mic_02", "label": "Recorder mic_02"},
    {"id": "birdnet", "label": "BirdNET"},
    {"id": "upload_worker", "label": "Cloud Sync Worker"},
]
