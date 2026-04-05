# Release Checklist

> **Status:** Normative (Mandatory) · **Scope:** Release Tagging & Quality Gates

Step-by-step guide for tagging a new Silvasonic release.

## 0. Release Type & Quality Gates

Every version bump **must** be classified as one of two types. The quality gates
differ accordingly.

### Feature Release (Minor or Major: `X.Y.0`)

Adds new functionality, changes behavior, or introduces new services. **All** of
the following are **mandatory** before tagging:

- [ ] **Changed-Path Test Audit** — Every new or modified code path has been explicitly reviewed and mapped to the appropriate verification tier (Unit for isolated logic, Integration for DB/Redis/service contracts, System for lifecycle/hardware). If no direct test is added, the reason must be stated explicitly.
- [ ] **No New Test Anti-Patterns in Changed Scope** — Tests added or modified for this release have been reviewed against `testing.md`. Mock-heavy verification, call-chain mirroring, and coverage-driven bloat were not introduced in the changed scope. Existing legacy anti-patterns outside the release scope were documented but do not require unrelated refactoring before release.
- [ ] **Critical Path Verification** — All new or changed state transitions, database queries, failure recovery paths, and hardware interactions are explicitly guarded by appropriate tests. Boilerplate or framework glue may remain indirectly tested only if it has no meaningful standalone contract and the relevant behavior is covered at a higher tier.
- [ ] **Smoke Tests** — Every service included in the release has a passing smoke test (`@pytest.mark.smoke`)
- [ ] **`just ci` passes** — Full CI pipeline (lint, type-check, all test tiers, container build, compose validation) runs cleanly
- [ ] **Hardware Tests** _(recommended)_ — If USB microphone hardware is available, run `just test-hw-all` (`@pytest.mark.system_hw_auto` and `.system_hw_manual`). These tests validate real device detection, profile matching, and container spawning with physical hardware. Not mandatory, but strongly recommended before any release that touches device detection or Recorder spawning.

> [!CAUTION]
> A Feature Release **MUST NOT** be tagged if any of the above gates fails.
> Fix all issues first, then re-run `just ci` until clean.

### Patch Release (Bug-Fix / Stabilization: `X.Y.Z` where `Z > 0`)

Bug fixes only. Pre-v1.0.0, internal behavior changes or architecture refactorings that enforce system stability and core directives (like data integrity) without introducing new user-facing features are permitted to maintain a clean baseline.

- [ ] **`just ci` passes**
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
| `uv.lock`                                       | **YES — Indirectly**             | Run `uv lock` to sync the lockfile after `pyproject.toml` bump  |

> [!IMPORTANT]
> After bumping the versions in `pyproject.toml` and `__init__.py`, you **MUST** run `uv lock` to update the lockfile. Otherwise, the `uv lock --check` step will fail.

---

## 2. Run All Checks

All checks **must pass** before tagging:

```bash
just ci
```

This includes:

- **Ruff** — Linting & Formatting
- **Mypy** — Type Checking
- **pytest** — Unit, Integration, System & Smoke Tests
- **pip-audit** — Dependency Security Audit
- **uv lock --check** — Lock File Consistency
- **Containerfile Lint** — Hadolint + Compose YAML Validation

> [!TIP]
> If you have a USB microphone connected, also run `just test-hw-all` to validate
> hardware detection, profile matching, and Recorder spawning with real devices.
> This is strongly recommended but not enforced by `just ci`.

If any check fails: **Fix → Commit → Re-run `just ci`**.

---

## 3. Commit & Tag

> **🚨 AI DIRECTIVE:** AI Agents **MUST NEVER** execute `git commit`, `git tag`, or `git push` autonomously. Agents must strictly format these commands in a copy-pasteable script block for the Human user to execute.

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
