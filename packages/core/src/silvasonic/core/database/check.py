"""Database connectivity health check."""

import structlog
from silvasonic.core.database.session import get_session
from sqlalchemy import text

logger = structlog.get_logger()


async def check_database_connection() -> bool:  # pragma: no cover — integration-tested
    """Attempt to connect to the database and execute a simple query.

    Returns:
        True if connection is successful, False otherwise.
    """
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("database_health_check_failed", error=str(e))
        return False
