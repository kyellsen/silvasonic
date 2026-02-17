import logging

from silvasonic.core.database.session import get_session
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def check_database_connection() -> bool:
    """Attempt to connect to the database and execute a simple query.

    Returns:
        True if connection is successful, False otherwise.
    """
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False
