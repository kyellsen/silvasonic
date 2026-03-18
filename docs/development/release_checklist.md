# Release Checklist

Step-by-step guide for tagging a new Silvasonic release.

---

## 0. Release Type & Quality Gates

Every version bump **must** be classified as one of two types. The quality gates
differ accordingly.

### Feature Release (Minor or Major: `X.Y.0`)

Adds new functionality, changes behavior, or introduces new services. **All** of
the following are **mandatory** before tagging:

- [ ] **100 % Unit Test Coverage** — `uv run pytest -m unit --cov` must report **100 %** statement coverage. Code that is inherently not unit-testable (DB connectivity, Redis loops, `asyncio.run()` entry points, etc.) **must** be marked with `# pragma: no cover` plus an inline justification referencing the integration test that covers the code (e.g. `# pragma: no cover — integration-tested (test_database.py)`). New `pragma` exclusions require review.
- [ ] **Unit Tests** — Every new feature has dedicated unit tests (`@pytest.mark.unit`)
- [ ] **Integration Tests** — Database interactions, service-to-service communication, and adjacent-service contracts are covered (`@pytest.mark.integration`)
- [ ] **System Tests** — Full-stack lifecycle tests pass with real Podman (`@pytest.mark.system`)
- [ ] **Smoke Tests** — Every service included in the release has a passing smoke test (`@pytest.mark.smoke`)
- [ ] **`just check-all` passes** — Full CI pipeline (lint, type-check, all test tiers, container build, compose validation) runs cleanly
- [ ] **Hardware Tests** _(recommended)_ — If USB microphone hardware is available, run `just test-hw` (`@pytest.mark.system_hw`). These tests validate real device detection, profile matching, and container spawning with physical hardware. Not mandatory, but strongly recommended before any release that touches device detection or Recorder spawning.

> [!CAUTION]
> A Feature Release **MUST NOT** be tagged if any of the above gates fails.
> Fix all issues first, then re-run `just check-all` until clean.

### Patch Release (Bug-Fix: `X.Y.Z` where `Z > 0`)

Bug fixes only — no new features, no behavior changes.

- [ ] **`just check-all` passes**
- [ ] **Regression test** for the fixed bug (recommended, ideally mandatory)

---

## 1. Set Version

Silvasonic has **one** central version file. All sub-packages (Controller, Recorder) derive their version dynamically via Hatch.

| File                                            | Update?                          | Description                                                  |
| ----------------------------------------------- | -------------------------------- | ------------------------------------------------------------ |
| `packages/core/src/silvasonic/core/__init__.py` | **YES — Single Source of Truth** | `__version__ = "X.Y.Z"`                                      |
| `pyproject.toml` (Root)                         | **YES**                          | `version = "X.Y.Z"`                                          |
| `ROADMAP.md` Line 3                             | **YES**                          | `> **Status:** vX.Y.Z — Milestone`                           |
| `README.md` Line 5                              | **YES**                          | `> **Status:** vX.Y.Z — Milestone`                           |
| `ROADMAP.md` Milestone table                    | **YES**                          | Set version status to `✅ Current`, mark previous as `✅ Done` |
| Sub-package `pyproject.toml`                    | **NO**                           | Version is derived dynamically from `silvasonic-core`        |

---

## 2. Run All Checks

All checks **must pass** before tagging:

```bash
just check-all
```

This includes:

- **Ruff** — Linting & Formatting
- **Mypy** — Type Checking
- **pytest** — Unit, Integration, System & Smoke Tests
- **pip-audit** — Dependency Security Audit
- **uv lock --check** — Lock File Consistency
- **Containerfile Lint** — Hadolint
- **Compose Validation** — Schema Check

> [!TIP]
> If you have a USB microphone connected, also run `just test-hw` to validate
> hardware detection, profile matching, and Recorder spawning with real devices.
> This is strongly recommended but not enforced by `just check-all`.

If any check fails: **Fix → Commit → Re-run `just check-all`**.

---

## 3. Commit & Tag

### Final Commit

Ensure all changes are committed:

```bash
git status                # No uncommitted changes
git add -A
git commit -m "release: vX.Y.Z — Milestone-Name"
```

### Create Annotated Tag

```bash
git tag -a vX.Y.Z -m "vX.Y.Z — Milestone-Name"
```

> **Important:** Always use **annotated tags** (`-a`), never lightweight tags. Annotated tags include author, date, and message.

### Push (Including Tag)

```bash
git push origin main
git push origin vX.Y.Z
```

---

## 4. Post-Release

- [ ] ROADMAP.md: Mark next version as `🔨 In Progress`
- [ ] Optionally create a GitHub Release (recommended from v1.0.0 onwards with CHANGELOG)
