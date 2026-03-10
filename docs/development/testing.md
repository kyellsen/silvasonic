# Testing Guide

> **Status:** Normative (Mandatory) · **Scope:** All Python packages and services

---

## 1. Test Markers

Every test function **MUST** have exactly one marker (AGENTS.md §6). Tests without a marker will be rejected in code review.

| Marker        | Description                                          | External Deps              | Typical Duration |
| ------------- | ---------------------------------------------------- | -------------------------- | ---------------- |
| `unit`        | Fast, isolated tests without external dependencies   | None (mocks only)          | < 1s per test    |
| `integration` | Tests with external services (DB, Redis)             | Testcontainers / Compose   | < 30s per test   |
| `smoke`       | Health checks against running containers             | Full stack (`just start`)  | < 30s total      |
| `e2e`         | Browser tests via Playwright                         | Full stack + Playwright    | < 60s per test   |

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
    e2e/            # @pytest.mark.e2e — browser tests (Playwright)
```

> [!IMPORTANT]
> A test file in `tests/unit/` **MUST** only contain `@pytest.mark.unit` tests. Mixing markers in a single directory is **FORBIDDEN**.

---

## 3. Running Tests

```bash
just test-unit       # Unit tests only (no external deps)
just test-int        # Integration tests (Testcontainers)
just test-smoke      # Smoke tests (full stack must be running)
just test-e2e        # End-to-end browser tests (Playwright)
just test-all        # Unit + Integration
just test            # Alias for test-all
```

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

### Smoke Tests

- Require the full Compose stack to be running (`just start`).
- Only test service health endpoints and basic connectivity (heartbeats in Redis).
- Must be idempotent — running them multiple times produces the same result.

### E2E Tests

- Use Playwright for browser automation.
- Test user-facing flows through the Web-Interface.
- Screenshots on failure for debugging.

---

## 5. Test Infrastructure

| Tool | Purpose |
| --- | --- |
| `pytest` | Test runner |
| `testcontainers` | Disposable PostgreSQL + Redis for integration tests |
| `polyfactory` | Pydantic model factories for test data generation |
| `playwright` | Browser automation for E2E tests |
| `pytest-timeout` | Global timeout per test (default: 120s) |
| `pytest-asyncio` | Async test support (auto mode) |

---

## 6. Naming Conventions

| Element | Convention | Example |
| --- | --- | --- |
| Test file | `test_<module>.py` | `test_controller.py` |
| Test class | `Test<Feature>` | `TestDeviceEvaluation` |
| Test function | `test_<behavior>` | `test_missing_profile_stays_pending` |

Test names should describe the **expected behavior**, not the implementation detail.

---

## See Also

- [AGENTS.md §6](../../AGENTS.md) — Testing rules (markers, directory structure)
- [AGENTS.md §5](../../AGENTS.md) — Approved test libraries
