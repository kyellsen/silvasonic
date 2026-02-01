import asyncio
import os
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from silvasonic.status_board.services import ContainerService, StatusService

router = APIRouter()

# Setup templates
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


@router.get("/workspace", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def workspace(request: Request) -> HTMLResponse:
    """Render the main workspace shell."""
    recorders = await ContainerService.get_recorders()
    return templates.TemplateResponse(
        request=request, name="workspace.html", context={"recorders": recorders}
    )


@router.get("/dashboard", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def dashboard(request: Request) -> HTMLResponse:
    """Render the dashboard partial with real status data."""
    # Parallelize status checks
    db_task = StatusService.check_database()
    redis_task = StatusService.check_redis()
    containers_task = ContainerService.get_containers()

    tcp_db, tcp_redis, containers = await asyncio.gather(db_task, redis_task, containers_task)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"tcp_db": tcp_db, "tcp_redis": tcp_redis, "containers": containers},
    )


@router.get("/services/recorders", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def list_recorders(request: Request) -> HTMLResponse:
    """List all discovered recorder services."""
    recorders = await ContainerService.get_recorders()
    return templates.TemplateResponse(
        request=request, name="recorders_list.html", context={"recorders": recorders}
    )


@router.get("/services/recorders/{container_id}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def recorder_detail(request: Request, container_id: str) -> HTMLResponse:
    """Show details for a specific recorder."""
    recorders = await ContainerService.get_recorders()
    target = next(
        (r for r in recorders if r["id"] == container_id or r["full_id"] == container_id), None
    )

    if not target:
        return HTMLResponse(
            "<div class='p-6 text-red-500'>Recorder not found.</div>",
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="service_recorder.html",
        context={"recorder": target},
    )


@router.get("/services/{service_name}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def service_detail(request: Request, service_name: str) -> HTMLResponse:
    """Render the service status page."""
    # Map service name to expected container name substring
    target_name = f"silvasonic-{service_name}"
    containers = await ContainerService.get_containers()

    # Find container
    container = None
    for c in containers:
        if any(target_name in name for name in c.get("Names", [])):
            container = c
            break

    if not container:
        return HTMLResponse(
            f"<div class='p-6 text-red-500'>Service '{service_name}' not found or container not running.</div>",
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="service_detail.html",
        context={
            "service_name": service_name,
            "container_id": container["Id"],
            "container": container,
        },
    )


@router.get("/services/{service_name}/logs", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def service_logs(request: Request, service_name: str) -> HTMLResponse:
    """Render the service logs page."""
    target_name = f"silvasonic-{service_name}"
    containers = await ContainerService.get_containers()

    container = None
    for c in containers:
        if any(target_name in name for name in c.get("Names", [])):
            container = c
            break

    if not container:
        return HTMLResponse(
            f"<div class='p-6 text-red-500'>Service '{service_name}' not found or container not running.</div>",
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="service_logs.html",
        context={"service_name": service_name, "container_id": container["Id"]},
    )


@router.get("/logs/{container_id}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def view_logs(request: Request, container_id: str) -> HTMLResponse:
    """Render the generic logs page for a container."""
    return templates.TemplateResponse(
        request=request, name="logs.html", context={"container_id": container_id}
    )


@router.get("/stream/{container_id}")  # type: ignore[untyped-decorator]
async def stream_logs(container_id: str) -> StreamingResponse:
    """Stream logs via Server-Sent Events (SSE)."""

    async def sse_generator() -> AsyncGenerator[str, None]:
        generator = ContainerService.stream_logs(container_id)
        try:
            async for line in generator:
                yield f"data: {line}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get("/events")  # type: ignore[untyped-decorator]
async def events(request: Request) -> StreamingResponse:
    """Stream status updates via SSE."""
    subscriber = request.app.state.subscriber
    return StreamingResponse(subscriber.stream_events(), media_type="text/event-stream")


@router.get("/health", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def health_check(request: Request) -> str:
    """Simple HTMX partial for health status."""
    return "<span class='text-green-500'>● System Operational</span>"
