from fastapi import APIRouter, HTTPException
from silvasonic.core.redis.publisher import RedisPublisher
from silvasonic.status_board.services import ContainerService

router = APIRouter(tags=["System"])


# --- SERVICE CONTROL ---


@router.post("/containers/{container_id}/{action}")
async def control_container(container_id: str, action: str) -> dict[str, str]:
    """Control a container (start/stop/restart)."""
    if action not in ["start", "stop", "restart"]:
        raise HTTPException(status_code=400, detail="Invalid action. Use start, stop, or restart")

    success = False
    if action == "start":
        success = await ContainerService.start_container(container_id)
    elif action == "stop":
        success = await ContainerService.stop_container(container_id)
    elif action == "restart":
        success = await ContainerService.restart_container(container_id)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to {action} container")

    return {"status": "success", "action": action, "container_id": container_id}


# --- SYSTEM ---


@router.post("/system/reload")
async def reload_system() -> dict[str, str]:
    """Trigger a system-wide configuration reload."""
    publisher = RedisPublisher(service_name="status-board-api")
    try:
        await publisher.publish_control(
            command="reload_config", initiator="api_user", target_service="controller"
        )
        return {"status": "success", "message": "Reload signal sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish reload signal: {e}") from e
