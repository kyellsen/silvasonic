"""Identifiers of rows created at runtime (ADR-0033, ADR-0037).

A UUIDv7 is unique without a central authority and sorts by creation time.
The station database is SQLite, which cannot generate one, so the
application does.  Python 3.14 brings ``uuid.uuid7``; until the services
move to it, the ``uuid6`` package supplies the generator.
"""

import uuid

from uuid6 import uuid7 as _uuid7


def uuid7() -> uuid.UUID:
    """Return a new RFC 9562 UUIDv7 as a standard-library ``uuid.UUID``."""
    return uuid.UUID(int=_uuid7().int)
