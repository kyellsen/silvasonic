# Testing Guide

> **Status:** Normative (Mandatory) · **Scope:** All Python packages and services

---

## 1. Test Markers

Every test function **MUST** have exactly one marker. Tests without a marker will be rejected in code review.

| Marker | Included in `just ci` | Target duration (guideline) |
| --- | --- | --- |
| `unit` | ✅ | < 1s/test |
| `integration` | ✅ | < 30s/test |
| `system` | ✅ | < 60s/test |
| `smoke` | ✅ | < 30s total |
| `e2e` | ✅ | < 60s/test |
| `system_hw_auto` | ❌ Never | < 60s/test |
| `system_hw_manual` | ❌ Never | < 60s/test |

> [!IMPORTANT]
> `system_hw_auto` and `system_hw_manual` tests are **never** included in CI or `just ci`.
> They require real USB microphone hardware. Run via `just test-hw` / `just test-hw-manual`.

---

## 2. Directory Structure

Test location **MUST** match the marker. Service-specific tests live inside the service package.
Only cross-cutting tests (multi-service, stack-level) belong in root `tests/`.

| Location | Markers |
| --- | --- |
| `packages/<pkg>/tests/unit/` | `@pytest.mark.unit` |
| `packages/<pkg>/tests/integration/` | `@pytest.mark.integration` |
| `services/<svc>/tests/unit/` | `@pytest.mark.unit` |
| `services/<svc>/tests/integration/` | `@pytest.mark.integration` |
| `tests/smoke/` | `@pytest.mark.smoke` |
| `tests/integration/` | `@pytest.mark.integration` (multi-service) |
| `tests/system/` | `.system`, `.system_hw_auto`, `.system_hw_manual` |
| `tests/e2e/` | `@pytest.mark.e2e` |

> [!IMPORTANT]
> Mixing markers in a single directory is **FORBIDDEN**.
> **Exception:** `tests/system/` contains `.system`, `.system_hw_auto` and `.system_hw_manual`
> because they share Podman socket, DB, and hardware-config fixtures via a common `conftest.py`.

---

## 3. Running Tests

### Individual Suites

```bash
just test-unit       # Unit tests only (no external deps)
just test-int        # Integration tests (Testcontainers)
just test-system     # System lifecycle tests (Podman + built images, no HW)
just test-hw         # Automated hardware tests (requires real USB microphone)
just test-hw-manual  # Interactive hardware tests (requires manual unplug/replug)
just test-hw-all     # All hardware tests (automated + manual)
just test-smoke      # Smoke tests (built images via Testcontainers)
just test-e2e        # End-to-end browser tests (Playwright)
just test            # Quick dev: Unit + Integration
just test-all        # All tests except hardware (Unit+Int+System+Smoke+E2E)
just test-cov-all    # Combined coverage map (Unit+Int+System+Smoke+E2E)
```

### Quality Gates

```bash
just c               # Fast dev check (< 10s):
                     #   Lock + Ruff + Mypy + Unit Tests
just v               # Verify for push (~ 35s):
                     #   Fast Check + DB-Integration Tests
just ci              # Full CI pipeline (> 4m):
                     #   Lock → Audit → Lint → Type → Unit → Int
                     #   → Containerfile → Build → System → Smoke → E2E
```

### When to Run What

| Situation              | Command            | What it covers                                  |
| ---------------------- | ------------------ | ----------------------------------------------- |
| During development     | `just test`        | Unit + Integration (quick feedback)             |
| Before every commit    | `just c`           | Lint, types, unit tests (no containers)         |
| Before push / PR       | `just v`           | Code Quality + Integration Tests                |
| Thorough test run      | `just test-all`    | All test suites except hardware                 |
| Verify Full CI         | `just ci`          | Full 12-stage pipeline incl. build              |
| Before release         | `just ci`          | All automated gates (see Release Checklist)     |
| Release test audit     | `just test-cov-all`| Combined coverage map for Changed-Path Audit    |
| With USB mic connected | `just test-hw-all` | Real hardware detection + spawning              |

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

### Hardware System Tests (`@pytest.mark.system_hw_auto` / `.system_hw_manual`)

- Test device detection pipeline with **real USB microphone hardware**.
- Each test session gets its own **isolated Podman network** (`silvasonic-hw-test-{id}`) via the `hw_redis` fixture.
- Require a USB-Audio device connected (e.g., UltraMic 384K).
- Skip automatically when no USB-Audio device is detected.
- **Fully isolated from production** — can run while `just start` is active.
- **Never** included in CI pipelines — run manually via `just test-hw` or `just test-hw-manual`.

### Smoke Tests

- Use `testcontainers` to start **built** container images in isolation (no `just start` needed).
- Require images to be built first (`just build` or pipeline Stage 9).
- Only test service health endpoints and basic connectivity (heartbeats in Redis).
- Must be idempotent — running them multiple times produces the same result.
- Do **NOT** test deep lifecycle behavior — that belongs in `system` tests.

### E2E Tests

- Use Playwright for browser automation.
- Test user-facing flows through the Web-Interface.
- Screenshots on failure for debugging.
- Planned for v0.9.0+ when the Web-Interface has sufficient coverage.

---

## 5. Test Quality & Anti-Patterns

> **Status:** Normative (Mandatory)
> This section defines the qualitative boundaries for tests. It is especially critical for AI-generated code.

### 5.1 Anti-Patterns (What Tests Must NOT Do)

The following patterns are **FORBIDDEN** and will lead to test rejection:
- **Existence/Import Tests:** Tests that only verify imports or whether a function exists without asserting observable behavior.
- **Trivial Equality:** Tests that only assert constants or default values (unless the value itself is an explicit domain contract).
- **Call-Chain Mirroring:** Tests that identically replicate internal ORM/framework logic or helper structures instead of testing visible behavior.
  _Bad:_ `assert mock_session.execute.call_args == select(Model).where(...)` —
  mirrors the ORM query instead of testing the returned domain result.
- **Mock-Heavy Verification:** Tests whose primary logic consists of setting up mocks rather than verifying domain logic. If mocking is substantially larger than the assertion, the test design is flawed.
- **Fragile Async Control:** Async or loop tests that rely on brittle `call_count` checks, artificial `CancelledError` injections, or timing tricks when more robust alternatives exist.

### 5.2 Delete vs. Refactor Rule

Particularly for AI-generated tests, distinguish carefully between fixing and deleting:
- **DELETE** if a test provides no clear business or architectural value.
- **DELETE** if a test artificially inflates line coverage but would not catch a real regression.
- **REFACTOR** if a test covers a valuable domain contract but is written in a brittle way.

### 5.3 Layer-Specific Quality Rules

- **Unit Tests (`@pytest.mark.unit`):**
  - Must test the behavior of small units, not the implementation details.
  - Zero I/O, zero database access, zero framework internals.
  - Minimize mocking: use fakes or data structures where possible.
- **Integration Tests (`@pytest.mark.integration`):**
  - Must use real PostgreSQL/Redis testcontainers. Mocking the database in integration tests is **FORBIDDEN**.
  - Must verify actual contracts between components and external dependencies.
- **System Tests (`@pytest.mark.system`):**
  - Must focus on full lifecycle effects and state transitions.
  - Must assert end results, not internal call sequences.

### 5.4 Guidelines for AI Agents

- **Check Before Adding:** Before an agent adds a new test, it must verify whether an existing higher-level test already covers the same failure space.
- **Prioritize Simplicity:** AI-generated tests must favor simplicity and readability over exhaustive completeness.
- **Avoid Coverage-Driven Bloat:** Do not generate tests solely to increase test coverage.
- **Document Intent:** New tests must clearly state (via naming or docstrings) the specific behavior or regression they are safeguarding.

---

## 6. `ci` Pipeline Stages

The `just ci` command runs these stages in order:

| Stage Name         | Critical | Description                                      |
| ------------------ | -------- | ------------------------------------------------ |
| Lock-File Check    | No       | `uv lock --check`                                |
| Dep Audit          | No       | `pip-audit` (skipped by default in dev)           |
| Containerfile Lint | No       | Hadolint + `podman-compose config` validation    |
| Ruff Lint          | Yes      | Linting + formatting                              |
| Mypy               | Yes      | Static type checking                              |
| Unit Tests         | Yes      | `@pytest.mark.unit` (parallel, coverage)          |
| Integration Tests  | Yes      | `@pytest.mark.integration` (testcontainers)       |
| Clear              | Always   | Clean workspace                                   |
| Build Images       | Always   | `just build`                                      |
| System Tests       | Yes      | `@pytest.mark.system` (real Podman, needs images) |
| Smoke Tests        | Yes      | `@pytest.mark.smoke` (testcontainers)             |
| E2E Tests          | Yes      | `@pytest.mark.e2e` (Playwright)                   |

---

## 7. Test Infrastructure

| Tool | Purpose |
| --- | --- |
| `pytest` | Test runner |
| `pytest-xdist` | Parallel test execution (`-n` workers) — see §10 |
| `testcontainers` | Disposable PostgreSQL + Redis for integration tests |
| `polyfactory` | Pydantic model factories for test data generation |
| `playwright` | Browser automation for E2E tests |
| `pytest-timeout` | Global timeout per test (default: 120s) |
| `pytest-asyncio` | Async test support (auto mode) |

---

## 8. Naming Conventions

| Element | Convention | Example |
| --- | --- | --- |
| Test file | `test_<module>.py` | `test_controller.py` |
| Test class | `Test<Feature>` | `TestDeviceEvaluation` |
| Test function | `test_<behavior>` | `test_missing_profile_stays_pending` |

Test names should describe the **expected behavior**, not the implementation detail.

---

## 9. Parallel Execution & Isolation

**Every test level is fully isolated.** All combinations can run in parallel — with each other and with `just start` (production stack).

### Isolation by Level

| Level | Container Infra | Network |
| --- | --- | --- |
| `unit` | None | None |
| `integration` | `testcontainers` | Random (auto) |
| `smoke` | `testcontainers` | `smoke_network` (random) |
| `system` | Podman CLI | `silvasonic-test-{run_id}` (per test) |
| `system_hw_auto` | Podman CLI | `silvasonic-hw-test-{session_id}` (per session) |
| `system_hw_manual` | Podman CLI | `silvasonic-hw-test-{session_id}` (per session) |
| `just start` | Compose | `silvasonic-net` (fixed) |

### Key Fixtures & Mechanisms

- `system_network` fixture — creates per-test Podman network, prevents DNS alias collisions between parallel system tests.
- `hw_redis` fixture — creates per-session Podman network for hardware tests.
- `TEST_RUN_ID` (UUID per session) / `run_id` (UUID per test) — prevent container name collisions.
- Owner label `io.silvasonic.owner=controller-test-<ID>` prevents `just stop` from removing test containers.
- `podman_run(network=...)` and `make_test_spec(..., network=...)` require the network parameter (compile-time guarantee).

---

## 10. Parallel Workers & DB Cleanup

Worker counts and their environment variable overrides are defined in [`scripts/test.py`](https://github.com/kyellsen/silvasonic/blob/main/scripts/test.py) — the **single source of truth**. Do **not** duplicate the defaults here.

Override example: `SILVASONIC_INTEGRATION_WORKERS=8 just test-int`

> [!WARNING]
> **System test hard ceiling:** The rootless Podman socket is a shared bottleneck.
> Too many workers cause `testcontainers` to hit 60s read timeouts on the Podman API.
> See `scripts/test.py` for current limits.

### Integration Test DB Cleanup

With `pytest-xdist`, each worker gets its own session-scoped `postgres_container` (via `testcontainers`). An **autouse** `_clean_db_tables` fixture calls a centralized `clean_database` helper from `silvasonic-test-utils`.

This helper dynamically queries the database for all application tables and truncates them using `RESTART IDENTITY CASCADE`. This automatically respects foreign key relationships and entirely removes the need to manually maintain cleanup lists when adding new tables to the schema.

---

## See Also

- [`scripts/test.py`](https://github.com/kyellsen/silvasonic/blob/main/scripts/test.py) — Single source of truth for test commands and worker counts
- [AGENTS.md §6](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md) — Testing core rules (markers, directory structure)
- [AGENTS.md §5](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md) — Approved test libraries
- [Release Checklist](release_checklist.md) — Quality gates per release type
