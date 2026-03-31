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

# 🔄 Stoppt und startet die Services neu (Recorder laufen weiter, ADR-0013)
restart:
    @{{ BOOTSTRAP_PYTHON }} scripts/stop.py --keep-tier2
    @{{ BOOTSTRAP_PYTHON }} scripts/start.py

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

# 🔍 Code Quality: Lock, Ruff, Mypy, Unit Tests (Fast, keine Container)
check:
    @{{ BOOTSTRAP_PYTHON }} scripts/check.py

# 🧬 Full CI Pipeline: Lint → Type → Unit → Int → Containerfile → Build → System → Smoke → E2E
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

# 🔧 System Lifecycle Tests (Podman + gebaute Images, keine Hardware nötig)
test-system:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system

# 🎤 Hardware System Tests (echtes USB-Mikrofon erforderlich)
test-hw:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw

# 🧪 Quick Dev Tests (Unit + Integration, ohne System/Smoke/E2E)
test:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py test

# 🏭 Alle Tests außer Hardware (Unit + Int + System + Smoke + E2E)
test-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py all

# 📈 Kombinierte Test-Coverage (Unit + Int + System + Smoke + E2E)
test-cov-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py cov-all

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

# ☢️  clean + .venv + alle Silvasonic Container/Volumes/Networks/Images löschen
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
