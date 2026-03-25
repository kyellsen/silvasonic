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
- Use `testcontainers` for DB + Redis, real `SilvasonicPodmanClient` for Podman.
- Mock `/proc/asound/cards` and sysfs to simulate device detection without hardware.
- Skip gracefully when Podman socket is absent or images aren't built.
- Tests cover: seeding, device scanning, profile matching, reconciliation, container start/stop.

### Hardware System Tests (`@pytest.mark.system_hw`)

- Test device detection pipeline with **real USB microphone hardware**.
- Require a USB-Audio device connected (e.g., UltraMic 384K).
- Skip automatically when no USB-Audio device is detected.
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
| 3     | Ruff Lint          | Yes      | Linting + formatting                              |
| 4     | Mypy               | Yes      | Static type checking                              |
| 5     | Unit Tests         | Yes      | `@pytest.mark.unit` (parallel, coverage)          |
| 6     | Integration Tests  | Yes      | `@pytest.mark.integration` (testcontainers)       |
| 7     | Containerfile Lint | No       | Hadolint (skipped if not installed)               |
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

### Safe Combinations (✅ run freely in parallel)

| Suite A | Suite B | Why it's safe |
| --- | --- | --- |
| `just test-unit` | **anything** | Pure in-process, no containers, no Podman |
| `just test-int` | `just test-int` | Testcontainers: ephemeral containers, random ports, own networks |
| `just test-int` | `just test-system` | Different container pools, no name collisions (`TEST_RUN_ID`) |
| `just test-int` | `just test-smoke` | Smoke uses own network (`smoke_network`) with distinct aliases |
| `just test-system` | `just test-system` | Each session gets unique `TEST_RUN_ID` → isolated container names+labels |
| `just test-system` | `just test-hw` | Both use `TEST_RUN_ID` for isolation |
| `just test-smoke` | `just test-smoke` | Testcontainers: fully ephemeral |
| `just stop` | **any test** | `stop.py` filters `owner=controller` (exact); test containers use `owner=controller-test-*` |

### Guarded Combinations (🛡️ automatic protection)

| Suite A | Suite B | Guard |
| --- | --- | --- |
| `just start` | `just test-system` | **Auto-abort**: system tests detect running production containers and exit immediately |
| `just start` | `just test-hw` | **Auto-abort**: same guard applies |

System and hardware tests share the `silvasonic-net` network with the production Compose stack. To prevent test containers from reaching production Redis, the system test `conftest.py` runs a **production stack guard** at import time. If any container with `io.silvasonic.owner=controller` is running, the test session aborts with a clear error message:

```
⚠️  Production containers are running: silvasonic-controller, ...
   System tests require an isolated environment.
   Run 'just stop' first, then re-run tests.
```

### Isolation Mechanisms

| Mechanism | Protects against |
| --- | --- |
| `TEST_RUN_ID` (UUID per session) | Container name collisions between parallel test runs |
| `io.silvasonic.owner=controller-test-<ID>` label | `just stop` accidentally removing test containers |
| Production stack guard (`conftest.py`) | Test containers reaching production Redis via shared network |
| Testcontainers (integration, smoke) | Shared DB/Redis — each session gets disposable containers |

---

## See Also

- [AGENTS.md §6](../../AGENTS.md) — Testing rules (markers, directory structure)
- [AGENTS.md §5](../../AGENTS.md) — Approved test libraries
- [Release Checklist](release_checklist.md) — Quality gates per release type

