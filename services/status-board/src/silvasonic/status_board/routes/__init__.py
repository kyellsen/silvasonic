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
    return templates.TemplateResponse("workspace.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def dashboard(request: Request) -> HTMLResponse:
    """Render the dashboard partial with real status data."""
    # Parallelize status checks
    db_task = StatusService.check_database()
    redis_task = StatusService.check_redis()
    containers_task = ContainerService.get_containers()

    tcp_db, tcp_redis, containers = await asyncio.gather(db_task, redis_task, containers_task)

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "tcp_db": tcp_db, "tcp_redis": tcp_redis, "containers": containers},
    )


@router.get("/logs/{container_id}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def view_logs(request: Request, container_id: str) -> HTMLResponse:
    """Render the log viewer partial for a specific container."""
    return templates.TemplateResponse(
        "logs.html", {"request": request, "container_id": container_id}
    )


@router.get("/stream/{container_id}")  # type: ignore[untyped-decorator]
async def stream_logs(container_id: str) -> StreamingResponse:
    """Stream logs via Server-Sent Events (SSE)."""

    async def sse_generator() -> AsyncGenerator[str, None]:
        generator = ContainerService.stream_logs(container_id)
        try:
            async for line in generator:
                # Format as SSE
                # Escape newlines for safety if needed, but usually just data: payload\n\n is enough
                # We strip the newline from the raw log line to avoid double spacing in the div logic if we used <pre>
                # But HTML div implies text.
                # clean_line = line.replace('"', '\\"') # minimal escaping for JSON-like safety if parsing
                # Actually, simpler: just send raw text. EventSource.data separates by \n\n.
                # If the log line contains \n, it might break the event.
                # Safer: Base64 or just one event per line.
                # Simplest for now: replacing \n with <br> or just sending multiline data?
                # EventSource spec: If data has newlines, it is concatenated with \n.
                # So we can just yield "data: " + line_with_newlines_replaced + "\n\n"

                # Let's simple yield the line.
                yield f"data: {line}\n\n"
        except asyncio.CancelledError:
            # Client disconnected
            pass

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get("/health", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
async def health_check(request: Request) -> str:
    """Simple HTMX partial for health status."""
    return "<span class='text-green-500'>● System Operational</span>"
