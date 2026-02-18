# Release Checklist

Step-by-step guide for tagging a new Silvasonic release.

---

## 1. Version setzen

Silvasonic hat **eine** zentrale Versionsdatei. Alle Sub-Packages (Controller, Recorder) leiten ihre Version dynamisch via Hatch ab.

| Datei                                           | Anpassen?                       | Beschreibung                                                      |
| ----------------------------------------------- | ------------------------------- | ----------------------------------------------------------------- |
| `packages/core/src/silvasonic/core/__init__.py` | **JA — Single Source of Truth** | `__version__ = "X.Y.Z"`                                           |
| `pyproject.toml` (Root)                         | **JA**                          | `version = "X.Y.Z"`                                               |
| `VISION.md` Zeile 5                             | **JA**                          | `> **Status:** vX.Y.Z — Milestone`                                |
| `README.md` Zeile 5                             | **JA**                          | `> **Status:** vX.Y.Z — Milestone`                                |
| `VISION.md` Roadmap-Tabelle                     | **JA**                          | Status der Version auf `✅ Current` setzen, vorherige auf `✅ Done` |
| Sub-Package `pyproject.toml`                    | **NEIN**                        | Version wird dynamisch aus `silvasonic-core` gelesen              |

---

## 2. Checks durchlaufen lassen

Alle Checks **müssen grün** sein bevor der Tag gesetzt wird:

```bash
just check-all
```

Das umfasst:

- **Ruff** — Linting & Formatting
- **Mypy** — Type Checking
- **pytest** — Unit, Integration & Smoke Tests
- **pip-audit** — Dependency Security Audit
- **uv lock --check** — Lock File Consistency
- **Containerfile Lint** — Hadolint
- **Compose Validation** — Schema Check

Falls ein Check fehlschlägt: **Fix → Commit → Erneut `just check-all`**.

---

## 3. Commit & Tag

### Finaler Commit

Stelle sicher, dass alle Änderungen committed sind:

```bash
git status                # Keine uncommitted changes
git add -A
git commit -m "release: vX.Y.Z — Milestone-Name"
```

### Annotated Tag setzen

```bash
git tag -a vX.Y.Z -m "vX.Y.Z — Milestone-Name"
```

> **Wichtig:** Immer **annotated tags** (`-a`) verwenden, keine lightweight tags. Annotated Tags enthalten Autor, Datum und Nachricht.

### Push (inkl. Tag)

```bash
git push origin main
git push origin vX.Y.Z
```

---

## 4. Post-Release

- [ ] VISION.md Roadmap: Nächste Version als `🔨 In Progress` markieren
- [ ] Ggf. GitHub Release erstellen (ab v1.0.0 mit CHANGELOG)
