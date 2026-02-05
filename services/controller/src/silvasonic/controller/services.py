import structlog
from silvasonic.controller.orchestrator import PodmanOrchestrator
from silvasonic.controller.settings import ControllerSettings
from silvasonic.core.database.models.system import SystemService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()
settings = ControllerSettings()  # type: ignore[call-arg]

# Default Service Registry (Baseline Configuration)
# These defaults are used to populate the database on first run.
REGISTRY: dict[str, dict[str, bool]] = {
    #     "birdnet": {"enabled": True},
    #     "weather": {"enabled": False},  # Requires hardware
    #     "batdetect": {"enabled": False},  # Specialized
    # "uploader": {"enabled": True},  # Core functionality usually
}


class ServiceManager:
    """Manages the lifecycle of Tier 2 generic services."""

    def __init__(self, orchestrator: PodmanOrchestrator) -> None:
        """Initialize the ServiceManager."""
        self.orchestrator = orchestrator

    async def _init_defaults(self, session: AsyncSession) -> None:
        """Ensure all registry services exist in the database."""
        result = await session.execute(select(SystemService))
        existing = {s.name for s in result.scalars().all()}

        for name, config in REGISTRY.items():
            if name not in existing:
                logger.info(
                    "registering_new_service", service=name, default_enabled=config["enabled"]
                )
                new_service = SystemService(
                    name=name,
                    enabled=config["enabled"],
                    status="stopped",
                )
                session.add(new_service)

        await session.flush()

    async def reconcile_services(self, session: AsyncSession) -> None:
        """Sync Database State -> Container State."""
        # 1. Ensure DB has all services
        await self._init_defaults(session)

        # 2. Get Desired State
        result = await session.execute(select(SystemService))
        db_services = result.scalars().all()
        desired_state = {s.name: s for s in db_services}

        # 3. Get Actual State
        # We need to filter out recorders, which are handled separately by Hardware logic
        active_containers = self.orchestrator.list_active_services()
        running_services = {}

        for c in active_containers:
            svc_name = c.get("service")
            if svc_name and svc_name != "recorder":
                running_services[svc_name] = c

        # 4. Reconcile

        # A. Start Missing
        for name, service in desired_state.items():
            if service.enabled:
                if name not in running_services:
                    # Spawn it
                    self._spawn_service(name)
                    service.status = "running"  # Optimistic update
                else:
                    # Check if running but marked stopped in DB?
                    # Or update DB status
                    service.status = "running"
            else:
                service.status = "stopped"

        # B. Stop Forbidden
        for name, container in running_services.items():
            # If not in DB, or disabled in DB -> Stop
            db_svc = desired_state.get(name)
            should_run = db_svc and db_svc.enabled

            if not should_run:
                logger.info("stopping_disabled_service", service=name)
                success = self.orchestrator.stop_service(container["id"])
                if success and db_svc:
                    db_svc.status = "stopped"

        # Commit logic is handled by caller (transaction scope) usually,
        # but here we might want to flush updates.
        # We rely on main loop to commit.

    def _spawn_service(self, service_name: str) -> None:
        """Spawn a registered service."""
        # Construct arguments
        image = f"silvasonic-{service_name}"  # Convention

        # Env Vars
        env = {
            "PYTHONUNBUFFERED": "1",
            # Inject Postgres/Redis connection info if needed?
            # Usually handled by default env or docker network links standard names
            "POSTGRES_HOST": "silvasonic-database",
            "REDIS_HOST": "silvasonic-redis",
            # Inject Host Data Dir for internal mapping
            "HOST_SILVASONIC_DATA_DIR": settings.HOST_DATA_DIR,
        }

        # Volumes
        # Standard: Logs
        # Host: <HOST_DATA_DIR>/<service>/logs -> Container: /var/log/silvasonic
        host_log_dir = f"{settings.HOST_DATA_DIR}/{service_name}/logs"

        volumes = [
            f"{host_log_dir}:/var/log/silvasonic:z",
        ]

        # Specific Volume Logic for Uploader
        # It needs access to its buffer (RW) and Recorder data (RO)
        # if service_name == "uploader":
        #     # 1. Buffer (RW)
        #     # Host: <HOST_DATA_DIR>/uploader/buffer -> Container: /data/uploader/buffer
        #     host_buffer = f"{settings.HOST_DATA_DIR}/uploader/buffer"
        #     volumes.append(f"{host_buffer}:/data/uploader/buffer:z")

        #     # 2. Recordings (RO) - To read files for upload
        #     # Host: <HOST_DATA_DIR>/recorder -> Container: /data/recorder
        #     # Note: Controller manages recorder subdirs, but uploader might need to scan all?
        #     # Governance says: "If a service needs data from another... must be mounted Read-Only."
        #     host_recordings = f"{settings.HOST_DATA_DIR}/recorder"
        #     volumes.append(f"{host_recordings}:/data/recorder:ro,z")

        success = self.orchestrator.spawn_service(
            service_name=service_name, image=image, env=env, volumes=volumes
        )

        if not success:
            logger.error("failed_to_spawn_service", service=service_name)
