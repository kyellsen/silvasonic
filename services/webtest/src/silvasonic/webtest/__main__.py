"""Silvasonic Web Test — FastAPI application entry point."""

# ruff: noqa: D101, D103

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from silvasonic.core.database.models.detections import Detection
from silvasonic.core.database.models.recordings import Recording, Upload
from silvasonic.core.database.models.system import Device, SystemConfig
from silvasonic.core.database.models.taxonomy import Taxonomy
from silvasonic.core.database.session import get_db
from silvasonic.core.redis import get_redis_connection
from silvasonic.core.service_context import ServiceContext
from silvasonic.webtest import __version__
from silvasonic.webtest.settings import WebTestSettings
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

logger = structlog.get_logger()

_settings = WebTestSettings()
WEB_TEST_PORT = _settings.WEB_TEST_PORT
REDIS_URL = _settings.REDIS_URL

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _settings.TEMPLATES_DIR
_STATIC_DIR = _settings.STATIC_DIR
_WORKSPACE_DIR = _settings.WORKSPACE_DIR

# BirdNet wiki images are served from a read-only mount (ADR-0008, ADR-0009)
# compose.yml: ${WORKSPACE}/birdnet/wiki:/app/birdnet-wiki:ro,z
_BIRDNET_WIKI_DIR = Path("/app/birdnet-wiki")
_BIRDNET_WIKI_IMG_DIR = Path("img")


def _parse_birdnet_label(label: str) -> tuple[str, str]:
    """Parse a BirdNET detection label into (scientific_name, common_name).

    BirdNET labels have the format: 'Turdus merula_Eurasian Blackbird'
    Returns ('Turdus merula', 'Eurasian Blackbird').
    If no underscore is found, returns (label, label).
    """
    if "_" in label:
        parts = label.split("_", 1)
        return parts[0].strip(), parts[1].strip()
    return label, label


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with ServiceContext(
        service_name="webtest",
        service_port=WEB_TEST_PORT,
        redis_url=REDIS_URL,
        heartbeat_interval=_settings.HEARTBEAT_INTERVAL_S,
        skip_health_server=True,
    ) as ctx:
        app.state.ctx = ctx
        logger.info("webtest_ready", port=WEB_TEST_PORT)
        yield


app = FastAPI(
    title="Silvasonic Web Test",
    description="Real frontend MVP using real DB endpoints.",
    version=__version__,
    lifespan=lifespan,
)

if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Mount BirdNet wiki directory for serving cached species images (ADR-0008, ADR-0009)
# Images are downloaded by birdnet/wiki_enricher.py into birdnet/wiki/img/
# Webtest mounts this directory as read-only (Consumer Principle, ADR-0009)
try:
    if _BIRDNET_WIKI_DIR.exists():
        app.mount(
            "/media/birdnet-wiki",
            StaticFiles(directory=str(_BIRDNET_WIKI_DIR)),
            name="birdnet-wiki",
        )
except Exception as e:
    logger.warning("failed_to_mount_birdnet_wiki", error=str(e))

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


async def get_redis_metrics(request: Request) -> dict[str, Any]:
    ctx = getattr(request.app.state, "ctx", None)
    metrics = {"cpu": 0, "ram": 0, "temp": 0, "disk": 0, "status": "offline", "uptime": "0h"}
    if not ctx:
        return metrics

    redis = await get_redis_connection(ctx.redis_url)
    if not redis:
        return metrics

    try:
        import time

        import psutil

        boot_time = psutil.boot_time()
        uptime_s = int(time.time() - boot_time)
        hours, remainder = divmod(uptime_s, 3600)
        minutes, _ = divmod(remainder, 60)
        metrics["uptime"] = f"{hours}h {minutes}m"

        raw = await redis.get("silvasonic:status:controller")
        if raw:
            data = json.loads(raw)
            meta = data.get("meta", {})
            host = meta.get("host_resources", {})
            if host:
                metrics["cpu"] = host.get("cpu_percent", 0)
                metrics["ram"] = host.get("memory_percent", 0)
                metrics["temp"] = 0
                metrics["disk"] = host.get("storage_percent", 0) or 0
            metrics["status"] = "online"
    except Exception:
        pass
    return metrics


async def get_station(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    station = {"name": "Silvasonic", "location": "Local", "status": "active"}
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "system_settings")
    )
    saved = result.scalar_one_or_none()
    if saved and isinstance(saved.value, dict) and "station_name" in saved.value:
        station["name"] = saved.value["station_name"]
    return station


async def get_settings(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    settings = {
        "station_name": "Silvasonic",
        "language": "en",
        "timezone": "UTC",
        "latitude": "0.0",
        "longitude": "0.0",
        "poweroff_on_low_battery": False,
        "livesound_enabled": False,
        "birdnet_enabled": True,
        "batdetect_enabled": False,
        "weather_enabled": False,
        "birdnet_min_confidence": "0.7",
        "birdnet_time_start": "",
        "birdnet_time_end": "",
        "batdetect_min_confidence": "0.7",
        "batdetect_time_start": "",
        "batdetect_time_end": "",
        "ui": {
            "theme": "silvadark",
            "show_weather": False,
            "show_bats": False,
            "show_livesound": False,
        },
        "recording_policy": {"min_free_gb": 5, "retain_days": 30, "delete_after_upload": False},
        "analysis": {"auto_detect": True, "birdnet_enabled": True},
        "cloud_sync": {"enabled": False, "sync_interval_m": 60, "wifi_only": True},
        "remote": {
            "name": "Default Remote",
            "target_type": "s3",
            "url": "s3://bucket",
            "username": "admin",
            "bandwidth_limit_kbps": "",
            "upload_window_start": "",
            "upload_window_end": "",
        },
        "user": {"username": "admin"},
    }
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "system_settings")
    )
    saved = result.scalar_one_or_none()
    if saved and isinstance(saved.value, dict):
        settings.update(saved.value)
    return settings


async def get_base_ctx(
    request: Request,
    session: AsyncSession = Depends(get_db),
    station: dict[str, str] = Depends(get_station),
    settings: dict[str, Any] = Depends(get_settings),
) -> dict[str, Any]:
    metrics = await get_redis_metrics(request)

    active_result = await session.execute(
        select(func.count(Device.name)).where(Device.enabled.is_(True), Device.status == "online")
    )
    active_recorders = active_result.scalar() or 0

    upload_result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "cloud_sync")
    )
    cfg = upload_result.scalar_one_or_none()
    upload_enabled = False
    if cfg and isinstance(cfg.value, dict):
        upload_enabled = cfg.value.get("enabled", False)

    pending_uploads = (
        await session.execute(select(func.count(Upload.id)).where(Upload.success.is_(False)))
    ).scalar() or 0
    backlog_count = (
        await session.execute(
            select(func.count(Recording.id)).where(Recording.file_processed.is_(None))
        )
    ).scalar() or 0

    oldest_unprocessed = (
        (
            await session.execute(
                select(Recording).where(Recording.file_processed.is_(None)).order_by(Recording.time)
            )
        )
        .scalars()
        .first()
    )
    if oldest_unprocessed and oldest_unprocessed.time:
        from datetime import datetime

        now = datetime.now(UTC)
        record_time = oldest_unprocessed.time
        if record_time.tzinfo is None:
            record_time = record_time.replace(tzinfo=UTC)
        delta = now - record_time
        index_age = f"{int(max(0, delta.total_seconds()) / 60)} min"
    else:
        index_age = "0 min"

    janitor_status = "error"
    ctx = getattr(request.app.state, "ctx", None)
    if ctx:
        redis = await get_redis_connection(ctx.redis_url)
        if redis:
            raw_processor = await redis.get("silvasonic:status:processor")
            if raw_processor:
                try:
                    pdata = json.loads(raw_processor)
                    if pdata.get("health", {}).get("status") == "ok":
                        janitor_status = "ok"
                except Exception:
                    pass

    return {
        "version": request.app.version,
        "station": station,
        "metrics": metrics,
        "active_recorders": active_recorders,
        "upload_enabled": upload_enabled,
        "pending_uploads": pending_uploads,
        "backlog_count": backlog_count,
        "index_age": index_age,
        "janitor_status": janitor_status,
        "alerts": [],
        "log_services": [
            {"id": "all", "name": "All Services"},
            {"id": "controller", "name": "Controller"},
            {"id": "processor", "name": "Processor"},
            {"id": "recorder", "name": "Recorder"},
            {"id": "birdnet", "name": "BirdNET Worker"},
        ],
        "inspector_services": [
            {
                "id": "controller",
                "name": "Controller",
                "status": "running" if metrics["status"] == "online" else "error",
                "task": "Orchestrator",
            },
            {
                "id": "processor",
                "name": "Processor",
                "status": "running" if janitor_status == "ok" else "error",
                "task": "Data Pipeline",
            },
        ],
        "ui_settings": settings.get("ui", {}),
    }


@app.get("/healthy", tags=["ops"])
async def healthy() -> dict[str, str]:
    return {"status": "ok", "service": "webtest"}


class DBTestPayload(BaseModel):
    key: str
    value: dict[str, str]


@app.post("/api/test-db", tags=["ops"])
async def test_db_connection(
    payload: DBTestPayload,
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    config = SystemConfig(key=payload.key, value=payload.value)
    session.add(config)
    await session.commit()
    result = await session.execute(select(SystemConfig).where(SystemConfig.key == payload.key))
    saved = result.scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=500, detail="Failed to read back from DB")
    return {"status": "success", "key": saved.key, "value": saved.value}


@app.get("/api/dashboard-metrics", response_class=HTMLResponse)
async def dashboard_metrics(
    request: Request,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    from datetime import datetime

    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    total_recordings = (await session.execute(select(func.count(Recording.id)))).scalar() or 0
    recordings_today = (
        await session.execute(select(func.count(Recording.id)).where(Recording.time >= today))
    ).scalar() or 0

    total_detections = (await session.execute(select(func.count(Detection.id)))).scalar() or 0
    detections_today = (
        await session.execute(select(func.count(Detection.id)).where(Detection.time >= today))
    ).scalar() or 0

    unique_species = (
        await session.execute(select(func.count(func.distinct(Detection.label))))
    ).scalar() or 0

    recent_detections = []
    recent_rows = (
        (await session.execute(select(Detection).order_by(desc(Detection.time)).limit(5)))
        .scalars()
        .all()
    )
    for d in recent_rows:
        recent_detections.append(
            {
                "label": d.common_name or d.label,
                "confidence": f"{d.confidence * 100:.0f}%",
                "time": d.time.strftime("%H:%M") if d.time else "",
                "color": "success" if d.confidence > 0.8 else "warning",
            }
        )

    service_statuses = []
    ctx = request.app.state.ctx
    if ctx:
        redis = await get_redis_connection(ctx.redis_url)
        if redis:
            keys = await redis.keys("silvasonic:status:*")
            import time

            now = time.time()
            for key in keys:
                raw = await redis.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        svc_id = data.get("instance_id", "unknown")
                        svc_name = data.get("service", svc_id).title()
                        ts = data.get("timestamp", now)
                        age = int(now - ts)
                        health = data.get("health", {}).get("status", "error")
                        activity = data.get("activity", "idle")
                        meta = data.get("meta", {})

                        extra = ""
                        if svc_name.lower() == "recorder" and "recording" in meta:
                            r_meta = meta["recording"]
                            if r_meta.get("active"):
                                extra = f"REC {r_meta.get('segments_promoted', 0)}"

                        service_statuses.append(
                            {
                                "id": svc_id,
                                "name": svc_name,
                                "status": "running" if health == "ok" else "error",
                                "activity": activity,
                                "age_s": age,
                                "extra": extra,
                            }
                        )
                    except Exception:
                        pass
    service_statuses.sort(key=lambda s: 0 if s["id"] == "controller" else 1)

    ctx_data = {
        **base_ctx,
        "total_recordings": total_recordings,
        "recordings_today": recordings_today,
        "total_detections": total_detections,
        "detections_today": detections_today,
        "unique_species": unique_species,
        "recent_detections": recent_detections,
        "service_statuses": service_statuses,
    }
    return templates.TemplateResponse(request, "_dashboard_content.html", ctx_data)


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, base_ctx: dict[str, Any] = Depends(get_base_ctx)
) -> HTMLResponse:
    ctx = {**base_ctx, "active": "dashboard"}
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/recorders", response_class=HTMLResponse)
async def recorders(
    request: Request,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    devices = (await session.execute(select(Device))).scalars().all()
    # Build list of dicts similar to mock data for template compatibility
    recorders_list = []
    for d in devices:
        # Get count of recordings
        count_res = await session.execute(
            select(func.count(Recording.id)).where(Recording.sensor_id == d.name)
        )
        rec_count = count_res.scalar() or 0
        recorders_list.append(
            {
                "id": d.name,
                "name": d.name,
                "status": d.status,
                "device": d.model,
                "files_today": rec_count,
                "profile": d.profile_slug or "Unknown",
                "sample_rate": d.config.get("sample_rate", 0) if isinstance(d.config, dict) else 0,
                "bit_depth": d.config.get("bit_depth", 0) if isinstance(d.config, dict) else 0,
                "channels": d.config.get("channels", 1) if isinstance(d.config, dict) else 1,
            }
        )

    ctx = {**base_ctx, "active": "recorders", "recorders": recorders_list}
    return templates.TemplateResponse(request, "recorders.html", ctx)


@app.get("/recorders/{recorder_id}", response_class=HTMLResponse)
async def recorder_detail(
    request: Request,
    recorder_id: str,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    d = (
        await session.execute(select(Device).where(Device.name == recorder_id))
    ).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Recorder not found")

    count_res = await session.execute(
        select(func.count(Recording.id)).where(Recording.sensor_id == d.name)
    )
    rec_count = count_res.scalar() or 0

    recorder = {
        "id": d.name,
        "name": d.name,
        "status": d.status,
        "device": d.model,
        "files_today": rec_count,
        "profile": d.profile_slug or "Unknown",
        "sample_rate": d.config.get("sample_rate", 0),
        "bit_depth": d.config.get("bit_depth", 0),
        "channels": d.config.get("channels", 1),
        "watchdog_restarts": 0,
    }

    ctx = {**base_ctx, "active": "recorders", "recorder": recorder}
    return templates.TemplateResponse(request, "recorder_detail.html", ctx)


@app.get("/processor", response_class=HTMLResponse)
async def processor(
    request: Request,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    # Get 10 most recent recordings
    recent_recs = (
        (await session.execute(select(Recording).order_by(desc(Recording.time)).limit(10)))
        .scalars()
        .all()
    )

    # Process them into indexer_files list for template
    indexer_files = []
    for r in recent_recs:
        filename = r.file_raw.split("/")[-1] if r.file_raw else "unknown.wav"
        indexer_files.append(
            {
                "filename": filename,
                "status": "processed" if r.file_processed else "indexed",
                "time": r.time.strftime("%H:%M:%S") if r.time else "",
                "size_mb": f"{r.filesize_raw / 1024 / 1024:.1f}" if r.filesize_raw else "0.0",
                "sensor": r.sensor_id,
            }
        )

    ctx = {
        **base_ctx,
        "active": "processor",
        "indexer_files": indexer_files,
        "retention_events": [],  # Can pull from logs or a retention table if exists
    }
    return templates.TemplateResponse(request, "processor.html", ctx)


@app.get("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    recent_uploads = (
        (await session.execute(select(Upload).order_by(desc(Upload.attempt_at)).limit(10)))
        .scalars()
        .all()
    )
    audit_log = []
    for u in recent_uploads:
        audit_log.append(
            {
                "time": u.attempt_at.strftime("%H:%M:%S") if u.attempt_at else "",
                "file": u.filename,
                "status": "success" if u.success else "failed",
                "message": u.error_message or "Uploaded successfully",
                "size_mb": "—",
            }
        )

    upload_status = {
        "provider": "Cloud Sync",
        "state": "active" if base_ctx["upload_enabled"] else "disabled",
        "queue_size": 0,
        "last_sync": audit_log[0]["time"] if audit_log else "Never",
        "today_gb": 0.0,
    }

    ctx = {**base_ctx, "active": "upload", "upload_status": upload_status, "audit_log": audit_log}
    return templates.TemplateResponse(request, "upload.html", ctx)


@app.get("/birds", response_class=HTMLResponse)
async def birds(
    request: Request,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    # Query real bird detections grouped by label for summary.
    stmt = (
        select(
            Detection.label,
            func.count(Detection.id).label("count"),
            func.max(Detection.confidence).label("max_conf"),
        )
        .where(Detection.worker == "birdnet")
        .group_by(Detection.label)
        .order_by(desc("count"))
        .limit(10)
    )
    summary_rows = (await session.execute(stmt)).all()

    # Resolve language from settings
    lang = base_ctx.get("ui_settings", {}).get("language", "en") or "en"
    if lang not in ("en", "de"):
        lang = "en"

    species_summary = []
    top_10 = []
    for row in summary_rows:
        label = row.label
        sci_name, common_en = _parse_birdnet_label(label)

        # Look up Taxonomy for common names + cached image
        trans_stmt = select(Taxonomy).where(Taxonomy.label == label)
        trans = (await session.execute(trans_stmt)).scalars().first()

        # Resolve display name: Taxonomy > Detection common_name > parsed label
        common = common_en
        if trans and isinstance(trans.common_names, dict):
            common = str(trans.common_names.get(lang, trans.common_names.get("en", common_en)))

        # Build image URL from cached Taxonomy.image_path (workspace)
        image_url = None
        if trans and trans.image_path:
            image_file = _BIRDNET_WIKI_DIR / _BIRDNET_WIKI_IMG_DIR / trans.image_path
            if image_file.exists():
                image_url = f"/media/birdnet-wiki/{_BIRDNET_WIKI_IMG_DIR}/{trans.image_path}"

        species_summary.append(
            {
                "id": label.replace(" ", "_"),
                "species_en": common,
                "species_sci": trans.scientific_name if trans else sci_name,
                "count": row.count,
                "last_seen": "Recently",
                "confidence": f"{row.max_conf * 100:.0f}%",
                "image_url": image_url,
            }
        )
        top_10.append({"name": common, "count": row.count})

    # Recent detections
    recent = (
        (
            await session.execute(
                select(Detection)
                .where(Detection.worker == "birdnet")
                .order_by(desc(Detection.time))
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    detections = []
    for d in recent:
        # Look up image for detection species (workspace)
        det_trans = (
            (await session.execute(select(Taxonomy).where(Taxonomy.label == d.label)))
            .scalars()
            .first()
        )
        det_image_url = None
        if det_trans and det_trans.image_path:
            det_img_file = _BIRDNET_WIKI_DIR / _BIRDNET_WIKI_IMG_DIR / det_trans.image_path
            if det_img_file.exists():
                det_image_url = (
                    f"/media/birdnet-wiki/{_BIRDNET_WIKI_IMG_DIR}/{det_trans.image_path}"
                )

        detections.append(
            {
                "time": d.time.strftime("%H:%M:%S") if d.time else "",
                "species_en": d.common_name or d.label,
                "species_sci": d.label,
                "confidence": d.confidence,
                "sensor": "Unknown",
                "image_url": det_image_url,
            }
        )

    ctx = {
        **base_ctx,
        "active": "birds",
        "species": species_summary,
        "detections": detections,
        "top_10": top_10,
        "rarest": [],
    }
    return templates.TemplateResponse(request, "birds.html", ctx)


@app.get("/birds/{species_id}", response_class=HTMLResponse)
async def bird_detail(
    request: Request,
    species_id: str,
    session: AsyncSession = Depends(get_db),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    # species_id uses underscores: "Turdus_merula_Eurasian_Blackbird"
    # Restore the original label by replacing _ with space
    label = species_id.replace("_", " ")
    sci_name, common_en = _parse_birdnet_label(label)

    lang = base_ctx.get("ui_settings", {}).get("language", "en") or "en"
    if lang not in ("en", "de"):
        lang = "en"

    # Compute aggregate stats from detections
    stats_stmt = select(
        func.count(Detection.id).label("count"),
        func.max(Detection.confidence).label("max_conf"),
        func.min(Detection.time).label("first_seen"),
        func.max(Detection.time).label("last_seen"),
    ).where(Detection.worker == "birdnet", Detection.label == label)
    stats = (await session.execute(stats_stmt)).one()

    # Recent detections
    recent = (
        (
            await session.execute(
                select(Detection)
                .where(Detection.worker == "birdnet", Detection.label == label)
                .order_by(desc(Detection.time))
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    detections = []
    for d in recent:
        detections.append(
            {
                "ts": d.time.isoformat() if d.time else "",
                "time": d.time.strftime("%H:%M:%S") if d.time else "",
                "species_sci": sci_name,
                "confidence": d.confidence,
                "sensor": "Unknown",
                "audio_file": d.recording_id,
            }
        )

    # Look up Taxonomy for cached wiki data
    trans = (
        (await session.execute(select(Taxonomy).where(Taxonomy.label == label))).scalars().first()
    )

    # Resolve display name
    common = common_en
    if trans and isinstance(trans.common_names, dict):
        common = str(trans.common_names.get(lang, trans.common_names.get("en", common_en)))

    # Image URL from cached path (workspace)
    image_url = None
    if trans and trans.image_path:
        image_file = _BIRDNET_WIKI_DIR / _BIRDNET_WIKI_IMG_DIR / trans.image_path
        if image_file.exists():
            image_url = f"/media/birdnet-wiki/{_BIRDNET_WIKI_IMG_DIR}/{trans.image_path}"

    # Cached description text (language-aware)
    description_html = None
    if trans and isinstance(trans.description, dict):
        description_html = trans.description.get(lang, trans.description.get("en"))

    # Common names in both languages for taxonomy box
    common_names = {}
    if trans and isinstance(trans.common_names, dict):
        common_names = trans.common_names

    species = {
        "id": species_id,
        "species_en": common,
        "species_sci": trans.scientific_name if trans else sci_name,
        "count": getattr(stats, "count", 0),
        "max_confidence": stats.max_conf or 0,
        "first_seen": stats.first_seen.isoformat() if stats.first_seen else "",
        "last_seen": stats.last_seen.isoformat() if stats.last_seen else "",
        "image_url": image_url,
        "image_source": trans.image_source if trans else None,
        "description_html": description_html,
        "common_names": common_names,
        "conservation_status": trans.conservation_status if trans else None,
        "wiki_url": f"https://{lang}.wikipedia.org/wiki/{sci_name.replace(' ', '_')}",
    }

    ctx = {**base_ctx, "active": "birds", "species": species, "detections": detections}
    return templates.TemplateResponse(request, "bird_detail.html", ctx)




@app.get("/bats", response_class=HTMLResponse)
async def bats(
    request: Request, base_ctx: dict[str, Any] = Depends(get_base_ctx)
) -> Response:
    if not base_ctx.get("ui_settings", {}).get("show_bats", False):
        return RedirectResponse(url="/", status_code=303)
    ctx = {
        **base_ctx,
        "active": "bats",
        "species": [],
        "detections": [],
        "top_10": [],
        "rarest": [],
    }
    return templates.TemplateResponse(request, "bats.html", ctx)


@app.get("/bats/{species_id}", response_class=HTMLResponse)
async def bat_detail(
    request: Request, species_id: str, base_ctx: dict[str, Any] = Depends(get_base_ctx)
) -> Response:
    if not base_ctx.get("ui_settings", {}).get("show_bats", False):
        return RedirectResponse(url="/", status_code=303)
    ctx = {**base_ctx, "active": "bats", "species": {"id": species_id}, "detections": []}
    return templates.TemplateResponse(request, "bat_detail.html", ctx)


@app.get("/weather", response_class=HTMLResponse)
async def weather(
    request: Request, base_ctx: dict[str, Any] = Depends(get_base_ctx)
) -> Response:
    if not base_ctx.get("ui_settings", {}).get("show_weather", False):
        return RedirectResponse(url="/", status_code=303)
    ctx = {**base_ctx, "active": "weather", "statistics": {}, "current": {}}
    return templates.TemplateResponse(request, "weather.html", ctx)


@app.get("/livesound", response_class=HTMLResponse)
async def livesound(
    request: Request, base_ctx: dict[str, Any] = Depends(get_base_ctx)
) -> Response:
    if not base_ctx.get("ui_settings", {}).get("show_livesound", False):
        return RedirectResponse(url="/", status_code=303)
    ctx = {**base_ctx, "active": "livesound", "recorders": []}
    return templates.TemplateResponse(request, "livesound.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
async def settings(
    request: Request,
    settings_data: dict[str, Any] = Depends(get_settings),
    base_ctx: dict[str, Any] = Depends(get_base_ctx),
) -> HTMLResponse:
    ctx = {**base_ctx, "active": "settings", "settings": settings_data}
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings/general")
async def save_general_settings(
    station_name: str = Form(...),
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "system_settings")
    )
    saved = result.scalar_one_or_none()

    if not saved:
        saved = SystemConfig(key="system_settings", value={"station_name": station_name})
        session.add(saved)
    else:
        new_val: dict[str, Any] = (
            dict(saved.value)
            if getattr(saved, "value", None) and isinstance(saved.value, dict)
            else {}
        )
        new_val["station_name"] = station_name
        saved.value = new_val

    await session.commit()
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request, base_ctx: dict[str, Any] = Depends(get_base_ctx)) -> HTMLResponse:
    ctx = {**base_ctx, "active": "about"}
    return templates.TemplateResponse(request, "about.html", ctx)


@app.get("/events/console")
async def console_events(
    request: Request,
    service: str = "controller",
) -> EventSourceResponse:
    ctx = getattr(request.app.state, "ctx", None)

    async def generator() -> AsyncGenerator[dict[str, str]]:
        if not ctx:
            yield {"data": json.dumps({"service": "system", "message": "Context missing."})}
            return

        redis = await get_redis_connection(ctx.redis_url)
        if not redis:
            yield {"data": json.dumps({"service": "system", "message": "Redis disconnected."})}
            return
        pubsub = redis.pubsub()
        await pubsub.subscribe("silvasonic:logs")

        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    try:
                        data_str = (
                            message["data"]
                            if isinstance(message["data"], str)
                            else message["data"].decode("utf-8")
                        )
                        data = json.loads(data_str)
                        if service and service != "all" and data.get("service") != service:
                            continue  # Filter

                        ts = data.get("timestamp", "")
                        if ts and "T" in ts:
                            ts = ts.split("T")[1][:8]

                        lvl = data.get("level", "info").lower()
                        svc = data.get("service", "unknown")
                        msg = data.get("message", "")

                        color_class = "text-green-400"
                        if lvl == "error" or lvl == "exception":
                            color_class = "text-error"
                        elif lvl == "warn" or lvl == "warning":
                            color_class = "text-warning"
                        elif lvl == "info":
                            color_class = "text-info"

                        html_line = (
                            f'<div><span class="opacity-50">[{ts}]</span> '
                            f'<span class="{color_class}">[{svc}]</span> {msg}</div>'
                        )
                        yield {"data": html_line}
                    except Exception:
                        yield {"data": f"<div>{message['data']}</div>"}
        finally:
            await pubsub.unsubscribe("silvasonic:logs")
            await pubsub.close()

    return EventSourceResponse(generator())


if __name__ == "__main__":  # pragma: no cover
    root_path = os.getenv("SILVASONIC_API_ROOT_PATH", "")
    uvicorn.run(
        "silvasonic.webtest.__main__:app",
        host="0.0.0.0",
        port=WEB_TEST_PORT,
        reload=False,
        log_level="info",
        root_path=root_path,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
