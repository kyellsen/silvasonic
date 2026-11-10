"""Create the station schema in a new database file (ADR-0037).

SQLite records the schema version in ``PRAGMA user_version``.  A file at
version 0 is new: the first connection to it applies ``schema.sql`` in one
``BEGIN IMMEDIATE`` transaction, so services that start at the same time
wait for each other instead of racing.

Changing the schema of an existing database needs a migration, which this
module does not provide (the tool is decided before v1.0.0, ADR-0033).
A version this code does not know stops the service.
"""

import sqlite3
from functools import cache
from importlib.resources import files
from typing import Any

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """The database file was created by another schema version."""


@cache
def schema_statements() -> tuple[str, ...]:
    """Return the statements of ``schema.sql``, without comments, in order."""
    sql = files("silvasonic.core.database").joinpath("schema.sql").read_text(encoding="utf-8")
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines():
        stripped = line.split("--", 1)[0].rstrip()
        if not stripped:
            continue
        buffer += stripped + "\n"
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        msg = f"schema.sql ends inside a statement: {buffer.strip()[:80]}"
        raise ValueError(msg)
    return tuple(statements)


def _user_version(cursor: Any) -> int:
    cursor.execute("PRAGMA user_version")
    row = cursor.fetchone()
    return int(row[0])


def ensure_schema(dbapi_connection: Any) -> None:
    """Apply the schema if the database is new; refuse an unknown version.

    Args:
        dbapi_connection: A DBAPI connection in autocommit mode
            (``isolation_level = None``), as the engine's connect hook has it.

    Raises:
        SchemaVersionError: If the file holds a schema version other than
            ``SCHEMA_VERSION``.
    """
    cursor = dbapi_connection.cursor()
    try:
        version = _user_version(cursor)
        if version == 0:
            cursor.execute("BEGIN IMMEDIATE")
            try:
                # Another service may have created the schema while we waited.
                if _user_version(cursor) == 0:
                    for statement in schema_statements():
                        cursor.execute(statement)
                    cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                cursor.execute("COMMIT")
            except BaseException:
                cursor.execute("ROLLBACK")
                raise
            version = _user_version(cursor)
        if version != SCHEMA_VERSION:
            msg = (
                f"database schema version {version}, this code expects {SCHEMA_VERSION}; "
                "the database needs a migration"
            )
            raise SchemaVersionError(msg)
    finally:
        cursor.close()
