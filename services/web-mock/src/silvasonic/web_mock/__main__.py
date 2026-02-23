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

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from silvasonic.core.service_context import ServiceContext
from silvasonic.web_mock import mock_data
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
    description="UI shell with hardcoded mock data — no DB or Redis required.",
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


def _base_ctx(request: Request, active: str = "dashboard") -> dict[str, object]:
    """Return context dict available on every page (station info, metrics)."""
    return {
        "active": active,
        "station": mock_data.STATION,
        "metrics": mock_data.SYSTEM_METRICS,
        "active_recorders": mock_data.ACTIVE_RECORDERS,
        "active_uploaders": mock_data.ACTIVE_UPLOADERS,
        "alerts": mock_data.ALERTS,
        "log_services": mock_data.LOG_SERVICES,
    }


# ---------------------------------------------------------------------------
# Health endpoint (replaces SilvaService /healthy)
# ---------------------------------------------------------------------------


@app.get("/healthy", tags=["ops"])
async def healthy() -> dict[str, str]:
    """Health probe for Podman / compose healthcheck."""
    return {"status": "ok", "service": "web-mock"}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Dashboard — real-time overview bento-grid."""
    ctx = _base_ctx(request, "dashboard")
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/recorders", response_class=HTMLResponse)
async def recorders(request: Request) -> HTMLResponse:
    """Recorders — bento-grid of recorder cards."""
    ctx = {**_base_ctx(request, "recorders"), "recorders": mock_data.RECORDERS}
    return templates.TemplateResponse(request, "recorders.html", ctx)


@app.get("/processor", response_class=HTMLResponse)
async def processor(request: Request) -> HTMLResponse:
    """Processor — tabbed view (Pipeline / Storage / Index)."""
    ctx = {**_base_ctx(request, "processor"), "metrics": mock_data.SYSTEM_METRICS}
    return templates.TemplateResponse(request, "processor.html", ctx)


@app.get("/uploaders", response_class=HTMLResponse)
async def uploaders(request: Request) -> HTMLResponse:
    """Uploaders — bento-grid of uploader cards."""
    ctx = {**_base_ctx(request, "uploaders"), "uploaders": mock_data.UPLOADERS}
    return templates.TemplateResponse(request, "uploaders.html", ctx)


@app.get("/birds", response_class=HTMLResponse)
async def birds(request: Request) -> HTMLResponse:
    """Birds — tabs: Discovery / Analyzer / Statistics."""
    ctx = {
        **_base_ctx(request, "birds"),
        "species": mock_data.BIRD_SPECIES_SUMMARY,
        "detections": mock_data.BIRD_DETECTIONS,
    }
    return templates.TemplateResponse(request, "birds.html", ctx)


@app.get("/bats", response_class=HTMLResponse)
async def bats(request: Request) -> HTMLResponse:
    """Bats — tabs: Discovery / Analyzer / Statistics."""
    ctx = {
        **_base_ctx(request, "bats"),
        "species": mock_data.BAT_SPECIES_SUMMARY,
        "detections": [],
    }
    return templates.TemplateResponse(request, "bats.html", ctx)


@app.get("/weather", response_class=HTMLResponse)
async def weather(request: Request) -> HTMLResponse:
    """Weather — tabs: Current / Correlations / Export."""
    ctx = _base_ctx(request, "weather")
    return templates.TemplateResponse(request, "weather.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request) -> HTMLResponse:
    """Settings — tabbed configuration."""
    ctx = {**_base_ctx(request, "settings"), "settings": mock_data.SETTINGS}
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request) -> HTMLResponse:
    """About — version & links."""
    ctx = _base_ctx(request, "about")
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

if __name__ == "__main__":
    uvicorn.run(
        "silvasonic.web_mock.__main__:app",
        host="0.0.0.0",
        port=WEB_MOCK_PORT,
        reload=False,
        log_level="info",
    )
