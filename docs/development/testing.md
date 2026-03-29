# Testing Guide

> **Status:** Normative (Mandatory) · **Scope:** All Python packages and services

---

## 1. Test Markers

Every test function **MUST** have exactly one marker (AGENTS.md §6). Tests without a marker will be rejected in code review.

| Marker      | Description                                          | External Deps                | Typical Duration | In `check-all` |
| ----------- | ---------------------------------------------------- | ---------------------------- | ---------------- | -------------- |
| `unit`      | Fast, isolated tests without external dependencies   | None (mocks only)            | < 1s per test    | ✅ Stage 5      |
| `integration` | Tests with external services (DB, Redis)           | Testcontainers / Compose     | < 30s per test   | ✅ Stage 6      |
| `system`    | Full-stack lifecycle tests with real Podman           | Podman socket + built images | < 60s per test   | ✅ Stage 10     |
| `system_hw` | Hardware-dependent system tests                      | Podman + real USB microphone | < 60s per test   | ❌ Never        |
| `smoke`     | Health checks against running containers             | Full stack (`just start`)    | < 30s total      | ✅ Stage 11     |
| `e2e`       | Browser tests via Playwright                         | Full stack + Playwright      | < 60s per test   | ✅ Stage 12     |

> [!IMPORTANT]
> `system_hw` tests are **never** included in CI or `just check-all`. They require real USB
> microphone hardware and must be run manually via `just test-hw`.

---

## 2. Directory Structure

Test location **MUST** match the marker. Service-specific tests live inside the service package. Only cross-cutting tests (multi-service interactions, stack-level health) belong in the root `tests/` directory.

```
packages/<pkg>/tests/
    unit/           # @pytest.mark.unit
    integration/    # @pytest.mark.integration

services/<svc>/tests/
    unit/           # @pytest.mark.unit
    integration/    # @pytest.mark.integration

tests/                # Cross-cutting tests only
    smoke/          # @pytest.mark.smoke — stack health checks
    integration/    # @pytest.mark.integration — multi-service
    system/         # @pytest.mark.system — full-stack lifecycle (Podman)
                    # @pytest.mark.system_hw — hardware system tests
    e2e/            # @pytest.mark.e2e — browser tests (Playwright, v0.8.0+)
```

> [!IMPORTANT]
> A test file in `tests/unit/` **MUST** only contain `@pytest.mark.unit` tests. Mixing markers in a single directory is **FORBIDDEN**.
> **Exception:** `tests/system/` contains both `@pytest.mark.system` and `@pytest.mark.system_hw` tests because they share Podman socket, DB, and hardware-config fixtures via a common `conftest.py`.

---

## 3. Running Tests

### Individual Suites

```bash
just test-unit       # Unit tests only (no external deps)
just test-int        # Integration tests (Testcontainers)
just test-system     # System lifecycle tests (Podman + built images, no HW)
just test-hw         # Hardware system tests (requires real USB microphone)
just test-smoke      # Smoke tests (built images via Testcontainers)
just test-e2e        # End-to-end browser tests (Playwright)
just test            # Quick dev: Unit + Integration
just test-all        # All tests except hardware (Unit+Int+System+Smoke+E2E)
```

### Quality Gates

```bash
just check           # Fast dev check (4 stages):
                     #   Lock + Ruff + Mypy + Unit Tests
just check-all       # Full CI pipeline (12 stages):
                     #   Lock → Audit → Lint → Type → Unit → Int
                     #   → Containerfile → Build → System → Smoke → E2E
```

### When to Run What

| Situation              | Command          | What it covers                                  |
| ---------------------- | ---------------- | ----------------------------------------------- |
| During development     | `just test`      | Unit + Integration (quick feedback)             |
| Before every commit    | `just check`     | Lint, types, unit tests (no containers)         |
| Thorough test run      | `just test-all`  | All test suites except hardware                 |
| Before push / PR       | `just check-all` | Full 12-stage pipeline incl. build              |
| Before release         | `just check-all` | All automated gates (see Release Checklist)     |
| With USB mic connected | `just test-hw`   | Real hardware detection + spawning              |

---

## 4. Writing Tests

### Unit Tests

- Use `unittest.mock` or `pytest-mock` for all external dependencies (DB, Redis, Podman, filesystem).
- No network calls, no containers, no filesystem side-effects.
- Each test should run in < 1 second.

### Integration Tests

- Use `testcontainers` for disposable PostgreSQL and Redis instances.
- Do **NOT** rely on the Compose stack — integration tests must be self-contained.
- Use `polyfactory` for generating Pydantic model instances as test data.

### System Tests (`@pytest.mark.system`)

- Test the full Controller lifecycle pipeline with **real Podman** but **mocked hardware**.
- Each test gets its own **isolated Podman network** (`silvasonic-test-{run_id}`) via the `system_network` fixture.
- Use `testcontainers` for DB + Redis (Controller tests), or `podman_run()` with the isolated network (Processor tests).
- Mock `/proc/asound/cards` and sysfs to simulate device detection without hardware.
- Skip gracefully when Podman socket is absent or images aren't built.
- Tests cover: seeding, device scanning, profile matching, reconciliation, container start/stop, crash recovery.
- **Fully isolated from production** — no shared network with `just start`.

### Hardware System Tests (`@pytest.mark.system_hw`)

- Test device detection pipeline with **real USB microphone hardware**.
- Each test session gets its own **isolated Podman network** (`silvasonic-hw-test-{id}`) via the `hw_redis` fixture.
- Require a USB-Audio device connected (e.g., UltraMic 384K).
- Skip automatically when no USB-Audio device is detected.
- **Fully isolated from production** — can run while `just start` is active.
- **Never** included in CI pipelines — run manually via `just test-hw`.

### Smoke Tests

- Require the full Compose stack to be running (`just start`).
- Only test service health endpoints and basic connectivity (heartbeats in Redis).
- Must be idempotent — running them multiple times produces the same result.

### E2E Tests

- Use Playwright for browser automation.
- Test user-facing flows through the Web-Interface.
- Screenshots on failure for debugging.
- Planned for v0.8.0+ when the Web-Interface has sufficient coverage.

---

## 5. `check-all` Pipeline Stages

The `just check-all` command runs 12 stages in order:

| Stage | Name               | Critical | Description                                      |
| ----- | ------------------ | -------- | ------------------------------------------------ |
| 1     | Lock-File Check    | No       | `uv lock --check`                                |
| 2     | Dep Audit          | No       | `pip-audit` (skipped by default in dev)           |
| 3     | Containerfile Lint | No       | Hadolint (skipped if not installed)               |
| 4     | Ruff Lint          | Yes      | Linting + formatting                              |
| 5     | Mypy               | Yes      | Static type checking                              |
| 6     | Unit Tests         | Yes      | `@pytest.mark.unit` (parallel, coverage)          |
| 7     | Integration Tests  | Yes      | `@pytest.mark.integration` (testcontainers)       |
| 8     | Clear              | Always   | Clean workspace                                   |
| 9     | Build Images       | Always   | `just build`                                      |
| 10    | System Tests       | Yes      | `@pytest.mark.system` (real Podman, needs images) |
| 11    | Smoke Tests        | Yes      | `@pytest.mark.smoke` (testcontainers)             |
| 12    | E2E Tests          | Yes      | `@pytest.mark.e2e` (Playwright)                   |

> [!NOTE]
> `system_hw` tests are intentionally excluded from this pipeline.
> Run `just test-hw` separately when hardware is available.

---

## 6. Test Infrastructure

| Tool | Purpose |
| --- | --- |
| `pytest` | Test runner |
| `pytest-xdist` | Parallel test execution (`-n` workers) — see §9 |
| `testcontainers` | Disposable PostgreSQL + Redis for integration tests |
| `polyfactory` | Pydantic model factories for test data generation |
| `playwright` | Browser automation for E2E tests |
| `pytest-timeout` | Global timeout per test (default: 120s) |
| `pytest-asyncio` | Async test support (auto mode) |

---

## 7. Naming Conventions

| Element | Convention | Example |
| --- | --- | --- |
| Test file | `test_<module>.py` | `test_controller.py` |
| Test class | `Test<Feature>` | `TestDeviceEvaluation` |
| Test function | `test_<behavior>` | `test_missing_profile_stays_pending` |

Test names should describe the **expected behavior**, not the implementation detail.

---

## 8. Parallel Execution & Isolation

**Every test level is fully isolated.** All combinations can run in parallel — with each other and with `just start` (production stack).

### Isolation by Level

| Level | Container Infra | Network | Ports | Parallel-safe? | Safe vs. `just start`? |
| --- | --- | --- | --- | --- | --- |
| `unit` | None | None | None | ✅ | ✅ |
| `integration` | `testcontainers` | Random (auto) | Random | ✅ | ✅ |
| `smoke` | `testcontainers` | `smoke_network` (random) | Random | ✅ | ✅ |
| `system` | Podman CLI | `silvasonic-test-{run_id}` (per test) | Random | ✅ | ✅ |
| `system_hw` | Podman CLI | `silvasonic-hw-test-{session_id}` (per session) | Random | ✅ | ✅ |
| `just start` | Compose | `silvasonic-net` | Fixed | — | ✅ |

### All Combinations: ✅ Safe

| Suite A | Suite B | Why it's safe |
| --- | --- | --- |
| `just test-unit` | **anything** | Pure in-process, no containers, no Podman |
| `just test-int` | **anything** | `testcontainers`: ephemeral containers, random ports, own networks |
| `just test-smoke` | **anything** | `testcontainers`: own `smoke_network`, distinct aliases (`test-database`, `test-redis`) |
| `just test-system` | **anything** | Per-test `silvasonic-test-{run_id}` network via `system_network` fixture |
| `just test-hw` | **anything** | Per-session `silvasonic-hw-test-{id}` network via `hw_redis` fixture |
| `just test-system` | `just start` | ✅ No shared network — test and prod are fully separated |
| `just test-hw` | `just start` | ✅ No shared network — test and prod are fully separated |
| `just stop` | **any test** | `stop.py` filters `owner=controller` (exact match); tests use `owner=controller-test-*` |

### Isolation Mechanisms

| Mechanism | Scope | Protects against |
| --- | --- | --- |
| `system_network` fixture | Per test function | DNS alias collisions between parallel system tests |
| `hw_redis` fixture | Per session | DNS alias collisions between HW tests and prod |
| `TEST_RUN_ID` (UUID per session) | Per session | Container name collisions between parallel runs |
| `run_id` (UUID per test) | Per test function | Container name collisions within a single session |
| `io.silvasonic.owner=controller-test-<ID>` | Per session | `just stop` accidentally removing test containers |
| `testcontainers.Network()` | Per session | Integration/smoke tests vs. everything else |
| `podman_run(network=...)` (required, no default) | Per call | Compile-time guarantee that no caller forgets the network |
| `make_test_spec(..., network=...)` (required kw) | Per call | Compile-time guarantee that no caller forgets the network |

> [!NOTE]
> The production stack guard (`_abort_if_prod_running()`) was removed. It is no longer needed
> because all system and hardware tests create their own isolated Podman networks and never
> share `silvasonic-net` with the production Compose stack.

---

## 9. Parallel Workers & Configuration

All `just test-*` commands delegate to [`scripts/test.py`](../../scripts/test.py) — the **single source of truth** for pytest invocations, worker counts, and coverage arguments.

### Worker Defaults

| Suite | Workers | Env Override | Rationale |
| --- | --- | --- | --- |
| `unit` | **8** | `SILVASONIC_UNIT_WORKERS` | Pure in-process, CPU-bound — scales linearly |
| `integration` | **6** | `SILVASONIC_INTEGRATION_WORKERS` | Each worker spawns its own TimescaleDB testcontainer |
| `system` | **6** | `SILVASONIC_SYSTEM_WORKERS` | Sweet-spot before Podman socket bottleneck (see below) |
| `smoke` | **1** (sequential) | — | Requires running Compose stack, no parallelism needed |
| `system_hw` | **1** (sequential) | — | Single USB mic, hardware-bound |
| `e2e` | **1** (sequential) | — | Browser tests, inherently sequential |

> [!WARNING]
> **System test hard ceiling: ~6–7 workers.** The rootless Podman socket is a shared bottleneck.
> At **8 workers**, `testcontainers` hits 60s read timeouts on the Podman API, causing most tests
> to SKIP or ERROR. Benchmarked on i9/16c/62GB: W6=140s ✅, W8=67s ❌ (socket timeout).

### Overriding Worker Counts

```bash
# Temporary override for a single run
SILVASONIC_INTEGRATION_WORKERS=8 just test-int

# Or export for the session
export SILVASONIC_UNIT_WORKERS=10
just check
```

> [!TIP]
> On a workstation with many cores (e.g. i9/16 cores, 64GB RAM), raising `INTEGRATION_WORKERS`
> to 6–8 can halve integration test runtime. Each additional worker spawns one extra
> TimescaleDB container (~200MB RAM).


### Integration Test DB Cleanup

With `pytest-xdist`, each worker gets its own session-scoped `postgres_container` (via `testcontainers`). Tests on the same worker share that DB and run sequentially. An **autouse** `_clean_db_tables` fixture (in each `conftest.py`) deletes all application rows between tests in FK-safe order, ensuring no cross-test contamination.

Affected `conftest.py` files:
- `services/processor/tests/integration/conftest.py`
- `services/controller/tests/integration/conftest.py`
- `tests/integration/conftest.py`

> [!IMPORTANT]
> When adding new tables to the database schema, you **MUST** add them to the `_CLEANUP_TABLES`
> tuple in each `conftest.py` above, respecting FK order (children before parents).

---

## See Also

- [`scripts/test.py`](../../scripts/test.py) — Single source of truth for test commands and worker counts
- [AGENTS.md §6](../../AGENTS.md) — Testing rules (markers, directory structure)
- [AGENTS.md §5](../../AGENTS.md) — Approved test libraries
- [Release Checklist](release_checklist.md) — Quality gates per release type

