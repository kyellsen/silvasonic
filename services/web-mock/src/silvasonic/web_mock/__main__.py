"""Silvasonic Web Mock — FastAPI application entry point.

Uses :class:`~silvasonic.core.service_context.ServiceContext` via FastAPI
``lifespan`` — the same infrastructure as SilvaService, but adapted for an
HTTP server whose event loop is owned by Uvicorn.

This is the production-ready pattern for the real Web-Interface (v0.8.0):
replace mock_data imports route-by-route with real async DB queries.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from silvasonic.core.database.models.system import SystemConfig
from silvasonic.core.database.session import get_db
from silvasonic.core.service_context import ServiceContext
from silvasonic.web_mock import mock_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WEB_MOCK_PORT = int(os.environ.get("SILVASONIC_WEB_MOCK_PORT", "8001"))
REDIS_URL = os.environ.get("SILVASONIC_REDIS_URL", "redis://redis:6379/0")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
# When running from installed package the templates are next to the module.
# In dev hot-reload the override mounts /app/templates → same path wins via uvicorn.
_TEMPLATES_DIR = Path(os.environ.get("SILVASONIC_TEMPLATES_DIR", str(_HERE / "templates")))
_STATIC_DIR = Path(os.environ.get("SILVASONIC_STATIC_DIR", str(_HERE / "static")))

# ---------------------------------------------------------------------------
# Lifespan — ServiceContext as async context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Service infrastructure setup/teardown via ServiceContext.

    This is the FastAPI-native equivalent of SilvaService._setup()/_teardown().
    Uses the identical ServiceContext internals — no code duplication.
    """
    async with ServiceContext(
        service_name="web-mock",
        service_port=WEB_MOCK_PORT,
        redis_url=REDIS_URL,
        skip_health_server=True,  # Uvicorn already serves /healthy on this port
    ) as ctx:
        app.state.ctx = ctx
        logger.info("web_mock_ready", port=WEB_MOCK_PORT)
        yield
    # teardown is called automatically by __aexit__


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Silvasonic Web Mock",
    description="UI shell with mock data for most views. Real DB for Settings persistence.",
    version="0.2.0",
    lifespan=lifespan,
)

# Static files & templates
# Directories will be mounted if they exist; gracefully skip otherwise (tests).
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Template context helper
# ---------------------------------------------------------------------------


def _base_ctx(
    request: Request, station: dict[str, str], active: str = "dashboard"
) -> dict[str, object]:
    """Return context dict available on every page (station info, metrics)."""
    return {
        "active": active,
        "version": request.app.version,
        "station": station,
        "metrics": mock_data.SYSTEM_METRICS,
        "active_recorders": mock_data.ACTIVE_RECORDERS,
        "active_uploaders": mock_data.ACTIVE_UPLOADERS,
        "alerts": mock_data.ALERTS,
        "log_services": mock_data.LOG_SERVICES,
        "inspector_services": mock_data.INSPECTOR_SERVICES,
    }


async def get_station(session: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Retrieve station info from DB, fallback to mock data."""
    station = mock_data.STATION.copy()
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "system_settings")
    )
    saved = result.scalar_one_or_none()
    if saved and isinstance(saved.value, dict) and "station_name" in saved.value:
        station["name"] = saved.value["station_name"]
    return station


async def get_settings(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Retrieve full settings from DB, merge with mock data."""
    settings = mock_data.SETTINGS.copy()
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == "system_settings")
    )
    saved = result.scalar_one_or_none()
    if saved and isinstance(saved.value, dict):
        settings.update(saved.value)
        if "station_name" in saved.value:
            settings["station_name"] = saved.value["station_name"]
    return settings


# ---------------------------------------------------------------------------
# Health endpoint (replaces SilvaService /healthy)
# ---------------------------------------------------------------------------


@app.get("/healthy", tags=["ops"])
async def healthy() -> dict[str, str]:
    """Health probe for Podman / compose healthcheck."""
    return {"status": "ok", "service": "web-mock"}


class DBTestPayload(BaseModel):
    """Payload for the /api/test-db diagnostic endpoint."""

    key: str
    value: dict[str, str]


@app.post("/api/test-db", tags=["ops"])
async def test_db_connection(
    payload: DBTestPayload,
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Diagnostic endpoint to verify read/write access to the database."""
    # Write
    config = SystemConfig(key=payload.key, value=payload.value)
    session.add(config)
    await session.commit()

    # Read
    result = await session.execute(select(SystemConfig).where(SystemConfig.key == payload.key))
    saved = result.scalar_one_or_none()
    if saved is None or getattr(saved, "key", None) is None:  # Fallback safety check
        raise HTTPException(status_code=500, detail="Failed to read back from DB")

    return {
        "status": "success",
        "key": saved.key,
        "value": saved.value,
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Dashboard — real-time overview bento-grid."""
    ctx = _base_ctx(request, station, "dashboard")
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/recorders", response_class=HTMLResponse)
async def recorders(
    request: Request, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Recorders — bento-grid of recorder cards."""
    ctx = {**_base_ctx(request, station, "recorders"), "recorders": mock_data.RECORDERS}
    return templates.TemplateResponse(request, "recorders.html", ctx)


@app.get("/recorders/{recorder_id}", response_class=HTMLResponse)
async def recorder_detail(
    request: Request, recorder_id: str, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Recorder detail view."""
    recorder = next((r for r in mock_data.RECORDERS if r.id == recorder_id), None)
    if not recorder:
        raise HTTPException(status_code=404, detail="Recorder not found")
    ctx = {
        **_base_ctx(request, station, "recorders"),
        "recorder": recorder,
        "metrics": mock_data.SYSTEM_METRICS,
    }
    return templates.TemplateResponse(request, "recorder_detail.html", ctx)


@app.get("/processor", response_class=HTMLResponse)
async def processor(
    request: Request, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Processor — unified view (Indexer / Storage / Retention)."""
    ctx = {
        **_base_ctx(request, station, "processor"),
        "metrics": mock_data.SYSTEM_METRICS,
        "indexer_files": mock_data.PROCESSOR_INDEXER_FILES,
        "retention_events": mock_data.PROCESSOR_RETENTION_EVENTS,
    }
    return templates.TemplateResponse(request, "processor.html", ctx)


@app.get("/uploaders", response_class=HTMLResponse)
async def uploaders(
    request: Request, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Uploaders — bento-grid of uploader cards."""
    ctx = {**_base_ctx(request, station, "uploaders"), "uploaders": mock_data.UPLOADERS}
    return templates.TemplateResponse(request, "uploaders.html", ctx)


@app.get("/uploaders/{uploader_id}", response_class=HTMLResponse)
async def uploader_detail(
    request: Request, uploader_id: str, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Uploader detail view."""
    uploader = next((u for u in mock_data.UPLOADERS if u.id == uploader_id), None)
    if not uploader:
        raise HTTPException(status_code=404, detail="Uploader not found")
    ctx = {
        **_base_ctx(request, station, "uploaders"),
        "uploader": uploader,
        "metrics": mock_data.SYSTEM_METRICS,
    }
    return templates.TemplateResponse(request, "uploader_detail.html", ctx)


@app.get("/birds", response_class=HTMLResponse)
async def birds(request: Request, station: dict[str, str] = Depends(get_station)) -> HTMLResponse:
    """Birds — tabs: Discovery / Analyzer / Statistics."""
    ctx = {
        **_base_ctx(request, station, "birds"),
        "species": mock_data.BIRD_SPECIES_SUMMARY,
        "detections": mock_data.BIRD_DETECTIONS,
        "top_10": mock_data.BIRD_TOP_10,
        "rarest": mock_data.BIRD_RAREST,
    }
    return templates.TemplateResponse(request, "birds.html", ctx)


@app.get("/birds/{species_id}", response_class=HTMLResponse)
async def bird_detail(
    request: Request, species_id: str, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Bird detail view including Wikipedia information."""
    species = next((s for s in mock_data.BIRD_SPECIES_SUMMARY if s["id"] == species_id), None)
    if not species:
        raise HTTPException(status_code=404, detail="Bird species not found")

    detections = [d for d in mock_data.BIRD_DETECTIONS if d.species_sci == species["species_sci"]]

    ctx = {
        **_base_ctx(request, station, "birds"),
        "species": species,
        "detections": detections,
    }
    return templates.TemplateResponse(request, "bird_detail.html", ctx)


@app.get("/bats", response_class=HTMLResponse)
async def bats(request: Request, station: dict[str, str] = Depends(get_station)) -> HTMLResponse:
    """Bats — tabs: Discovery / Analyzer / Statistics."""
    ctx = {
        **_base_ctx(request, station, "bats"),
        "species": mock_data.BAT_SPECIES_SUMMARY,
        "detections": mock_data.BAT_DETECTIONS,
        "top_10": mock_data.BAT_TOP_10,
        "rarest": mock_data.BAT_RAREST,
    }
    return templates.TemplateResponse(request, "bats.html", ctx)


@app.get("/bats/{species_id}", response_class=HTMLResponse)
async def bat_detail(
    request: Request, species_id: str, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Bat detail view including Wikipedia information."""
    species = next((s for s in mock_data.BAT_SPECIES_SUMMARY if s.get("id") == species_id), None)
    if not species:
        raise HTTPException(status_code=404, detail="Bat species not found")

    detections = [d for d in mock_data.BAT_DETECTIONS if d.species_sci == species["species_sci"]]

    ctx = {
        **_base_ctx(request, station, "bats"),
        "species": species,
        "detections": detections,
    }
    return templates.TemplateResponse(request, "bat_detail.html", ctx)


@app.get("/weather", response_class=HTMLResponse)
async def weather(request: Request, station: dict[str, str] = Depends(get_station)) -> HTMLResponse:
    """Weather — tabs: Overview / Current / Statistics / Correlation."""
    stats = mock_data.WEATHER_STATISTICS
    current_vals = {k: v[-1] for k, v in stats.items() if isinstance(v, list)}

    ctx = {
        **_base_ctx(request, station, "weather"),
        "statistics": stats,
        "current": current_vals,
    }
    return templates.TemplateResponse(request, "weather.html", ctx)


@app.get("/livesound", response_class=HTMLResponse)
async def livesound(
    request: Request, station: dict[str, str] = Depends(get_station)
) -> HTMLResponse:
    """Livesound — View live audio from all recorders."""
    ctx = {
        **_base_ctx(request, station, "livesound"),
        "recorders": mock_data.RECORDERS,
    }
    return templates.TemplateResponse(request, "livesound.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
async def settings(
    request: Request,
    station: dict[str, str] = Depends(get_station),
    settings_data: dict[str, Any] = Depends(get_settings),
) -> HTMLResponse:
    """Settings — tabbed configuration."""
    ctx = {**_base_ctx(request, station, "settings"), "settings": settings_data}
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings/general")
async def save_general_settings(
    station_name: str = Form(...),
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Save general settings including station name."""
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
async def about(request: Request, station: dict[str, str] = Depends(get_station)) -> HTMLResponse:
    """About — version & links."""
    ctx = _base_ctx(request, station, "about")
    return templates.TemplateResponse(request, "about.html", ctx)


# ---------------------------------------------------------------------------
# SSE — fake console log stream
# ---------------------------------------------------------------------------


@app.get("/events/console")
async def console_events(
    request: Request,
    service: str = "controller",
) -> EventSourceResponse:
    """Server-Sent Events stream for the footer console.

    Cycles through FAKE_LOG_LINES indefinitely, filtering by ``service``.
    Replace with real Redis SUBSCRIBE in the actual web-interface.
    """

    async def generator() -> AsyncGenerator[dict[str, str], None]:
        lines = [
            ln
            for ln in mock_data.FAKE_LOG_LINES
            if json.loads(ln).get("service") == service
            or service not in [s["id"] for s in mock_data.LOG_SERVICES]
        ] or mock_data.FAKE_LOG_LINES  # fallback: all lines

        idx = 0
        while True:
            if await request.is_disconnected():
                break
            line = lines[idx % len(lines)]
            yield {"data": line}
            idx += 1
            await asyncio.sleep(1.5)

    return EventSourceResponse(generator())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    uvicorn.run(
        "silvasonic.web_mock.__main__:app",
        host="0.0.0.0",
        port=WEB_MOCK_PORT,
        reload=False,
        log_level="info",
    )
