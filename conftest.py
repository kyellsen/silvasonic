"""Root conftest.py — re-exports shared test-utils fixtures for all test paths.

pytest automatically discovers this file at the project root, making the
session-scoped container fixtures available to every test in ``testpaths``
(packages/*, services/*, tests/*) without explicit imports.
"""

from silvasonic.test_utils.containers import (  # noqa: F401
    postgres_container,
    redis_container,
    shared_network,
)
