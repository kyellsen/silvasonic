# ==============================================================================
# Silvasonic justfile
# ==============================================================================

set shell := ["bash", "-euo", "pipefail", "-c"]

# System Python for bootstrapping (before .venv exists)
BOOTSTRAP_PYTHON := "python3"

# .env is loaded by the Python scripts (scripts/compose.py)

# ==============================================================================
# TARGETS
# ==============================================================================

# 🛟  Zeigt diese Hilfe an
[private]
default:
    @just --list

# 🛠️  Initialisiert das Projekt (uv sync, hooks, workspace)
init:
    @{{ BOOTSTRAP_PYTHON }} scripts/init.py

# ==============================================================================
# CONTAINER LIFECYCLE (Podman)
# ==============================================================================

# 🔨 Baut die Container-Images
build:
    @{{ BOOTSTRAP_PYTHON }} scripts/build.py

# 🚀 Startet die Silvasonic Services
start:
    @{{ BOOTSTRAP_PYTHON }} scripts/start.py

# 🛑 Stoppt alle Silvasonic Services
stop:
    @{{ BOOTSTRAP_PYTHON }} scripts/stop.py

# 🔄 Stoppt und startet die Services neu
restart: stop start

# 📜 Zeigt die aggregierten Logs aller Services an
logs:
    @{{ BOOTSTRAP_PYTHON }} scripts/logs.py

# 📊 Zeigt den Status aller Services an
status:
    @{{ BOOTSTRAP_PYTHON }} scripts/status.py

# 🧨 Factory Reset (Clean, Init, Build, Start)
reset: clean init build start

# ==============================================================================
# CODE QUALITY
# ==============================================================================

# 🔧 Führt Auto-Fixer aus (Ruff Format, Lint Fixes)
fix:
    @{{ BOOTSTRAP_PYTHON }} scripts/fix.py

# 🔍 Nur Ruff Lint (Read-Only, kein Auto-Fix)
lint:
    @{{ BOOTSTRAP_PYTHON }} scripts/lint.py

# 🔍 Code Quality: Ruff, Mypy, Unit & Integration Tests (Fast)
check:
    @{{ BOOTSTRAP_PYTHON }} scripts/check.py

# 🧬 Full CI Pipeline: Lint → Type → Unit → Integration → Clear → Build → Smoke → E2E
check-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/check_all.py

# ==============================================================================
# TESTING
# ==============================================================================

# 🧪 Führt schnelle Unit-Tests aus (Mocked, ohne externe Services)
test-unit:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py unit

# 🐢 Führt Integrationstests aus (Testcontainers startet DB automatisch!)
test-int:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py integration

# 💨 Smoke Tests (Testcontainers — self-contained, kein just start nötig)
test-smoke:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py smoke

# 🏭 Führt alle Tests aus (Unit + Integration, ohne E2E/Smoke)
test-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py all

# 🧪 Alias für test-all
test:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py all

# 🕸️  Führt End-to-End Playwright Tests aus
test-e2e:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py e2e

# ==============================================================================
# MAINTENANCE & DOCS
# ==============================================================================

# 🧹 Räumt Root-Verzeichnis auf (.trash/ Quarantäne) und löscht Caches
clear:
    @{{ BOOTSTRAP_PYTHON }} scripts/clear.py

# 🧼 clear + Container-Volumes löschen (Storage-Reset)
clean:
    @{{ BOOTSTRAP_PYTHON }} scripts/clean.py

# ☢️  clean + .venv + Silvasonic-Images löschen (Full Reset)
nuke:
    @{{ BOOTSTRAP_PYTHON }} scripts/nuke.py

# 🗑️  Entfernt dangling Container-Images
prune:
    @{{ BOOTSTRAP_PYTHON }} scripts/prune.py

# 📚 Startet den lokalen MkDocs Server inkl. Live-Reload
docs:
    @echo "Starting docs server on http://localhost:8085..."
    @uv run mkdocs serve -a localhost:8085 --open

# 📦 Baut die statische Dokumentation (Output: site/)
docs-build:
    @uv run mkdocs build

# ==============================================================================
# FRONTEND (Tailwind CSS)
# ==============================================================================

# 🎨 Baut das Tailwind CSS für web-mock (einmalig, minified)
css-build:
    @cd services/web-mock && npm run css:build

# 👁️  Tailwind CSS Watch-Mode (auto-rebuild bei Template-/CSS-Änderungen)
css-watch:
    @cd services/web-mock && npm run css:watch
