import asyncio
import logging
import socket
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.status_board.config import settings
from silvasonic.status_board.routes import router

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_heartbeat(publisher: RedisPublisher) -> None:
    """Background task to publish status heartbeats."""
    while True:
        try:
            await publisher.publish_status(
                status="online",
                activity="monitoring",
                message="Status Board Active",
                meta={"port": settings.PORT, "dev_mode": settings.DEV_MODE},
            )
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle, performing startup checks."""
    # Startup check
    if not settings.DEV_MODE:
        logger.critical("Status Board Service is for DEV_MODE only. Shutting down.")
        sys.exit(1)

    logger.info(f"Starting Status Board in DEV_MODE. Listening on port {settings.PORT}")

    # Initialize Publisher
    publisher = RedisPublisher(service_name="status-board", instance_id=socket.gethostname())
    await publisher.publish_lifecycle("started", reason="Service startup")

    # Start Heartbeat
    heartbeat_task = asyncio.create_task(run_heartbeat(publisher))

    yield

    # Shutdown logic
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    await publisher.publish_lifecycle("stopping", reason="Service shutdown")


app = FastAPI(
    title="Silvasonic Status Board",
    lifespan=lifespan,
    docs_url=None,  # Clean UI, no docs needed for this internal tool
    redoc_url=None,
)

# Mount static files
try:
    app.mount(
        "/static", StaticFiles(packages=[("silvasonic.status_board", "static")]), name="static"
    )
except Exception:
    # Fallback if packages mount fails (e.g. running locally without install)
    import os

    static_path = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")

app.include_router(router)


@app.get("/")  # type: ignore[untyped-decorator]
async def root() -> RedirectResponse:
    """Redirect root to the workspace."""
    return RedirectResponse(url="/workspace")


if __name__ == "__main__":
    uvicorn.run("silvasonic.status_board.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
