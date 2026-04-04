# Service Blueprint — Guide for New Python Services

> **Purpose:** This document defines the **mandatory** structure, patterns, and shared
> components for every Python-based service in the Silvasonic project.
> New services **MUST** follow this blueprint to ensure full consistency with
> `controller` and `recorder`.

---

## 1. Directory Layout

Every service lives in `services/<name>/` and **must** follow this exact tree:

```
services/<name>/
├── Containerfile
├── README.md
├── pyproject.toml
├── src/
│   └── silvasonic/
│       └── <name>/
│           ├── __init__.py
│           ├── __main__.py
│           └── py.typed
└── tests/
    ├── integration/
    └── unit/
        └── test_<name>.py
```

| File                        | Purpose                                                            |
| --------------------------- | ------------------------------------------------------------------ |
| `__init__.py`               | Package docstring only: `"""Silvasonic <Name> Service Package."""` |
| `__main__.py`               | Service entry point — async lifecycle (see §3)                     |
| `py.typed`                  | PEP 561 marker — enables downstream type checking                  |
| `Containerfile`             | Container build recipe (see §5)                                    |
| `README.md`                 | Service-specific documentation                                     |
| `tests/unit/test_<name>.py` | Unit tests with 100% coverage target (see §7)                      |


## 2. `pyproject.toml` — Package Definition

Every service uses **hatchling** as build backend and declares `silvasonic-core` as
its only workspace dependency:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "silvasonic-<name>"
description = "<one-line description>"
readme = "README.md"
requires-python = ">=3.13"
dependencies = ["silvasonic-core"]
dynamic = ["version"]

[tool.hatch.version]
path = "https://github.com/kyellsen/silvasonic/blob/main/packages/core/src/silvasonic/core/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/silvasonic"]
```

### Workspace Registration

The new service **must** be registered in the root `pyproject.toml`:

1. `[project] dependencies` — add `"silvasonic-<name>"`
2. `[tool.uv.sources]` — add `silvasonic-<name> = { workspace = true }`
3. `[tool.uv.workspace] members` already auto-discovers via `"services/*"`


## 3. Service Lifecycle (`__main__.py`)

Every service **must** subclass `SilvaService` (see [ADR-0019](../adr/0019-unified-service-infrastructure.md)):

```python
from silvasonic.core.service import SilvaService


class MyService(SilvaService):
    """<Name> Service — <one-line description>."""

    service_name = "<name>"
    service_port = <PORT>          # See port_allocation.md

    async def run(self) -> None:
        """Service-specific logic — runs after all infrastructure is ready."""
        self.health.update_status("main", True, "running")

        while not self._shutdown_event.is_set():
            # Your domain logic here
            await asyncio.sleep(1)

    def get_extra_meta(self) -> dict[str, Any]:
        """Optional: add service-specific fields to heartbeat meta."""
        return {"my_metric": 42}


if __name__ == "__main__":
    MyService().start()
```

The `SilvaService` base class handles the full lifecycle automatically:

1. **Logging** — `configure_logging()` (structlog, Rich in dev / JSON in prod)
2. **Health Server** — HTTP `/healthy` on `:service_port` (Podman probes)
3. **Resource Collector** — per-process CPU/memory/threads via `psutil`
4. **Redis Connection** — best-effort via `get_redis_connection()` (skipped if unavailable)
5. **Heartbeat Loop** — fire-and-forget, periodic (`SET` + `PUBLISH` to Redis, interval: see `DEFAULT_HEARTBEAT_INTERVAL_S` in `heartbeat.py`)
6. **`run()`** — your service logic (override this)
7. **Graceful Shutdown** — SIGTERM / SIGINT → `_shutdown_event.set()`

> [!IMPORTANT]
> Services **MUST NOT** call lifecycle methods directly. The base class calls them
> in the correct order during `start()`. Only override `run()` and optionally
> `get_extra_meta()`.


## 4. Shared Components from `silvasonic-core`

Services **MUST NOT** reimplement any of the following. Import and use exclusively
from `silvasonic.core`:

| Module         | Import                                                     | Purpose                                         |
| -------------- | ---------------------------------------------------------- | ----------------------------------------------- |
| Service        | `silvasonic.core.service.SilvaService`                     | Unified lifecycle base class (ADR-0019)         |
| Heartbeat      | `silvasonic.core.heartbeat.HeartbeatPublisher`             | Async fire-and-forget Redis heartbeats          |
| Heartbeat      | `silvasonic.core.heartbeat.HeartbeatPayload`               | Pydantic model for heartbeat JSON schema        |
| Redis          | `silvasonic.core.redis.get_redis_connection`               | Best-effort connect, returns `None` on failure  |
| Logging        | `silvasonic.core.logging.configure_logging`                | Structured logging (Rich in dev, JSON in prod)  |
| Health         | `silvasonic.core.health.HealthMonitor`                     | Thread-safe singleton for component status      |
| Health         | `silvasonic.core.health.start_health_server`               | Background HTTP server on `/healthy`            |
| Resources      | `silvasonic.core.resources.ResourceCollector`              | Per-process CPU/memory/storage metrics          |
| Resources      | `silvasonic.core.resources.HostResourceCollector`          | Host-level metrics (Controller only)            |
| Settings       | `silvasonic.core.settings.DatabaseSettings`                | Pydantic-based config from env vars             |
| Config Schemas | `silvasonic.core.config_schemas.*`                         | Pydantic models for `system_config` JSONB blobs |
| Database       | `silvasonic.core.database.session.get_session`             | Async SQLAlchemy session (context manager)      |
| Database       | `silvasonic.core.database.session.get_db`                  | FastAPI dependency for DB sessions              |
| Database       | `silvasonic.core.database.check.check_database_connection` | Health probe for DB connectivity                |
| Models         | `silvasonic.core.database.models.*`                        | Shared SQLAlchemy ORM models                    |


## 5. Containerfile

All Python service Containerfiles follow this **identical** structure:

```containerfile
FROM python:3.13-slim-bookworm

WORKDIR /app

# 1. System dependencies (always include curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    # ... service-specific packages here ...
    && rm -rf /var/lib/apt/lists/*

# 2. UV installer (pinned version!)
COPY --from=ghcr.io/astral-sh/uv:0.10.3 /uv /uvx /bin/

# 3. Copy workspace files
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/<name>/ services/<name>/

# 4. Install with uv
RUN uv sync --frozen --no-dev --no-editable --package silvasonic-<name>

# 5. Environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE <PORT>

ENTRYPOINT ["python", "-m"]
CMD ["silvasonic.<name>"]
```

> [!WARNING]
> **UV version** (`0.10.3`) **must** match across all Containerfiles. When upgrading,
> update all services at once.

### Mandatory Rules

- **Base image:** `python:3.13-slim-bookworm` (default for all services)
  - **Exception:** ML worker services (e.g., BirdNET) MAY use `python:3.11-slim-bookworm`
    when hardware-specific ML libraries (e.g., `tflite-runtime` on aarch64) lack wheels for
    Python ≥ 3.12. This exception **requires** a documented ADR. See
    [ADR-0028](../adr/0028-python-version-flexibility-ml-workers.md).
- **Build context:** Always the repo root (`.`), never the service directory
- `curl` is always required (healthcheck)
- `packages/` is always copied (contains `silvasonic-core`)
- `PYTHONUNBUFFERED=1` and `PYTHONDONTWRITEBYTECODE=1` are always set


## 6. Compose Integration

> **IMPORTANT**
> Only **Tier 1 (Infrastructure)** services should be added to `compose.yml`.
> Immutable **Tier 2 (Application)** containers (e.g., Recorder, Uploader, BirdNET) are managed dynamically by the Controller and **MUST NOT** be placed in `compose.yml`.

### `compose.yml` (Tier 1 Only)

Add a new service block following the established pattern:

```yaml
  <name>:
    container_name: silvasonic-<name>
    build:
      context: .
      dockerfile: services/<name>/Containerfile
    restart: unless-stopped
    env_file: .env
    environment:
      POSTGRES_HOST: database
    ports:
      - "${SILVASONIC_<NAME>_PORT:-<PORT>}:<PORT>"
    depends_on:
      database:
        condition: service_healthy
    networks:
      - silvasonic-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:<PORT>/healthy"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s
```

### `compose.override.yml` (Development)

Add volume mounts for hot-reload:

```yaml
  <name>:
    environment:
      PYTHONPATH: /app/develop/service:/app/develop/core
    volumes:
      - ./services/<name>/src:/app/develop/service:z
      - ./packages/core/src:/app/develop/core:z
```

### `.env.example`

Add the port variable:

```
SILVASONIC_<NAME>_PORT=<PORT>
```

See [Port Allocation](../arch/port_allocation.md) for port assignment rules.


## 7. Testing

### Test File Structure

Tests reside in `services/<name>/tests/unit/test_<name>.py` and **must**:

1. Use `@pytest.mark.unit` on every class/function
2. Cover all code paths — **100% coverage target**
3. Follow the established test class structure:

```python
"""Unit tests for silvasonic-<name> service — 100 % coverage."""

import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.unit
class TestPackage:
    """Basic package-level tests."""

    def test_package_importable(self) -> None:
        """Package is importable."""
        import silvasonic.<name>
        assert silvasonic.<name> is not None


@pytest.mark.unit
class TestMonitorSomething:
    """Tests for monitor coroutines."""
    # Mock asyncio.sleep with CancelledError to test one loop iteration


@pytest.mark.unit
class TestMain:
    """Tests for the main() coroutine."""
    # Test lifecycle wiring + signal handling
    # Test __main__ guard with runpy
```

### Running Tests

```bash
just test-unit     # Fast, mocked, parallel (4 workers)
just test-int      # Integration (Testcontainers, needs Podman)
just test-system   # System lifecycle (real Podman + built images, no HW)
just test-hw-all   # Hardware system tests (real USB mic required)
just test-smoke    # Against running stack (just start first)
just test-all      # All tests except hardware (Unit+Int+System+Smoke+E2E)
```

> For full test marker documentation, see [Testing Guide](testing.md).


## 8. Naming Conventions Summary

| Aspect            | Pattern                  | Example                    |
| ----------------- | ------------------------ | -------------------------- |
| Service directory | `services/<name>/`       | `services/analyzer/`       |
| PyPI package name | `silvasonic-<name>`      | `silvasonic-analyzer`      |
| Python import     | `silvasonic.<name>`      | `silvasonic.analyzer`      |
| Compose service   | `<name>`                 | `analyzer`                 |
| Container name    | `silvasonic-<name>`      | `silvasonic-analyzer`      |
| Port env var      | `SILVASONIC_<NAME>_PORT` | `SILVASONIC_ANALYZER_PORT` |

> See also [AGENTS.md §3](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md) for the full naming policy.


## 9. Checklist for a New Service

Use this checklist when adding a new service:

- [ ] `services/<name>/` directory with full layout (§1)
- [ ] `pyproject.toml` with hatchling + `silvasonic-core` dep (§2)
- [ ] Root `pyproject.toml` updated (dependency + source) (§2)
- [ ] `__main__.py` follows lifecycle pattern (§3)
- [ ] Uses **only** shared `silvasonic.core` modules (§4)
- [ ] `Containerfile` follows template exactly (§5)
- [ ] `compose.yml` service block added (§6)
- [ ] `compose.override.yml` dev mounts added (§6)
- [ ] `.env.example` port variable added (§6)
- [ ] `docs/arch/port_allocation.md` updated (§6)
- [ ] Unit tests at 100% coverage (§7)
- [ ] `just check` passes (lint + type + tests)
- [ ] `just check-all` passes (full CI pipeline incl. build + smoke)
