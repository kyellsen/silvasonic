"""Silvasonic test utilities — shared fixtures and helpers for integration tests.

This package provides session-scoped ``pytest`` fixtures for:

- A shared Docker/Podman network
- A station database file (SQLite, with the real Silvasonic schema)
- A Redis container

Import fixtures in your ``conftest.py`` or use them directly::

    from silvasonic.test_utils.containers import station_db

The canonical way to consume these fixtures project-wide is via the root
``conftest.py``, which pytest discovers automatically for all test paths.
"""

__all__: list[str] = []
