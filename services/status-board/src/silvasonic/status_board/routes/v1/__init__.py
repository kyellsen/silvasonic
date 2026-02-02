from fastapi import APIRouter
from silvasonic.status_board.routes.v1.devices import router as devices_router
from silvasonic.status_board.routes.v1.profiles import router as profiles_router
from silvasonic.status_board.routes.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")

router.include_router(devices_router)
router.include_router(profiles_router)
router.include_router(system_router)
