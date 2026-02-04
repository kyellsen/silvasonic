# Testing Guide

This guide describes the tiered testing strategy in Silvasonic.

## 1. Test Types & Locations

| Type | Location | Purpose | Dependencies |
|------|----------|---------|--------------|
| **Unit** | `services/*/tests/unit/`<br>`packages/*/tests/unit/` | Fast verification of internal logic. | **Mocks** only. No DB/Redis. |
| **Integration** | `services/*/tests/integration/`<br>`packages/*/tests/integration/`<br>`tests/integration/` | "Grey-box" component testing. | **Testcontainers** (Postgres, Redis).<br>No direct `subprocess` calls to Podman/Docker! |
| **E2E** | `tests/e2e/` | "Black-box" full system testing. | **Full Stack** + Browser (Playwright). |

## 2. Running Tests (Make Shortcuts)

We provide optimized `make` commands for daily workflows:

- **`make test`**: Runs **Unit Tests** only (Fast ⚡ - < 5s).
- **`make test-int`**: Runs **Integration Tests** only (Slow 🐢 - requires Docker).
- **`make test-e2e`**: Runs **E2E Tests** only (Browser 🕸️).
- **`make check`**: Runs Lint + Types + Unit Tests (Recommended Pre-Push).
- **`make check-full`**: Runs **EVERYTHING** (Lint, Types, Unit, Integration, E2E).

## 3. Running Tests (Native Pytest)

For debugging or running specific tests, use `uv run pytest` directly.

### Run Unit Tests (Exclude Slow Tests)
```bash
uv run pytest -m "not integration" --ignore=tests/e2e
```

### Run Integration Tests Only
```bash
uv run pytest -m integration
```

### Run E2E Tests Only
```bash
uv run pytest tests/e2e
```

### Run a Specific File
```bash
uv run pytest services/controller/tests/unit/test_profiles.py
```

## 4. Pre-Commit Hooks
Our hooks ensure code quality automatically:
- **Pre-Commit**: Runs `fix` (Formatter) and `test` (Unit Tests).
- **Pre-Push**: Runs `check` (Lint, Types, Unit Tests).
