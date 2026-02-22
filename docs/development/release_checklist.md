# Release Checklist

Step-by-step guide for tagging a new Silvasonic release.

---

## 1. Set Version

Silvasonic has **one** central version file. All sub-packages (Controller, Recorder) derive their version dynamically via Hatch.

| File                                            | Update?                          | Description                                                  |
| ----------------------------------------------- | -------------------------------- | ------------------------------------------------------------ |
| `packages/core/src/silvasonic/core/__init__.py` | **YES — Single Source of Truth** | `__version__ = "X.Y.Z"`                                      |
| `pyproject.toml` (Root)                         | **YES**                          | `version = "X.Y.Z"`                                          |
| `VISION.md` Line 5                              | **YES**                          | `> **Status:** vX.Y.Z — Milestone`                           |
| `README.md` Line 5                              | **YES**                          | `> **Status:** vX.Y.Z — Milestone`                           |
| `VISION.md` Roadmap table                       | **YES**                          | Set version status to `✅ Current`, mark previous as `✅ Done` |
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
- **pytest** — Unit, Integration & Smoke Tests
- **pip-audit** — Dependency Security Audit
- **uv lock --check** — Lock File Consistency
- **Containerfile Lint** — Hadolint
- **Compose Validation** — Schema Check

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

- [ ] VISION.md Roadmap: Mark next version as `🔨 In Progress`
- [ ] Optionally create a GitHub Release (recommended from v1.0.0 onwards with CHANGELOG)
