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
alias s := setup
setup:
    @{{ BOOTSTRAP_PYTHON }} scripts/setup.py

# ==============================================================================
# CONTAINER LIFECYCLE (Podman)
# ==============================================================================

# 🔨 Baut die Container-Images
alias b := build
build *services:
    @{{ BOOTSTRAP_PYTHON }} scripts/build.py {{services}}

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

# 🔄 Startet einen bestimmten Service neu (z.B. just rs api)
rs service:
    @{{ BOOTSTRAP_PYTHON }} -c 'import sys; sys.path.insert(0, "./scripts"); from compose import compose; compose("restart", "{{service}}")'

# 📜 Zeigt die aggregierten Logs aller Services an
logs:
    @{{ BOOTSTRAP_PYTHON }} scripts/logs.py

# 📊 Zeigt den Status aller Services an
status:
    @{{ BOOTSTRAP_PYTHON }} scripts/status.py

# 🧨 Factory Reset (Clean, Init, Build, Start)
reset: clean setup build start

# ==============================================================================
# CODE QUALITY
# ==============================================================================

# 🔧 Run the auto-fixers (ruff format, lint fixes)
fix *args:
    @{{ BOOTSTRAP_PYTHON }} scripts/fix.py {{args}}

# 🔍 Nur Ruff Lint (Read-Only, kein Auto-Fix)
lint:
    @{{ BOOTSTRAP_PYTHON }} scripts/lint.py

# 📈 Prints the repository Lines of Code statistics
loc:
    @uv run scripts/loc.py

# 🔍 Nur statische Analyse & Unit Tests -> < 10s
alias c := check
check *targets:
    @{{ BOOTSTRAP_PYTHON }} scripts/check.py {{targets}}

# 🕵️ Verify (Code Quality + Integration Tests) -> ~35s
alias v := verify
verify *targets:
    @{{ BOOTSTRAP_PYTHON }} scripts/check.py --verify {{targets}}

# 🧬 Full CI Pipeline: Lint → Type → Unit → Int → Containerfile → Build → System → Smoke → E2E
ci:
    @{{ BOOTSTRAP_PYTHON }} scripts/ci.py

# ==============================================================================
# TESTING
# ==============================================================================

# 🧪 Run the fast unit tests (mocked, no external services)
test-unit:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py unit

# 🐢 Run the integration tests (testcontainers starts the DB automatically)
test-int:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py integration

# 💨 Smoke tests (testcontainers — self-contained, no 'just start' needed)
test-smoke:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py smoke

# 🔧 System lifecycle tests (Podman + built images, no hardware needed)
test-system:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system

# 🎤 Hardware system tests (automated, no input prompts)
test-hw:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw_auto

# 🔌 Interactive hardware system tests (manual unplugging at the console)
test-hw-manual:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw_manual

# 🤖 All hardware tests (automated and manual combined)
test-hw-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw_all

# 🧪 Quick dev tests (unit + integration, no system/smoke/e2e)
test:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py test

# 🏭 All tests except hardware (unit + int + system + smoke + e2e)
test-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py all

# 📈 Kombinierte Test-Coverage (Unit + Int + System + Smoke + E2E)
test-cov-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py cov-all

# 🕸️  Run the end-to-end Playwright tests
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
    @uv run mkdocs serve -a 0.0.0.0:8085 --open

# 📦 Baut die statische Dokumentation (Output: site/)
docs-build:
    @uv run mkdocs build

# ==============================================================================
# FRONTEND (Tailwind CSS)
# ==============================================================================

# 🎨 Build the Tailwind CSS for web-mock (one-shot, minified)
css-build:
    @cd services/web-mock && npm run css:build

# 👁️  Tailwind CSS Watch-Mode (auto-rebuild bei Template-/CSS-Änderungen)
css-watch:
    @cd services/web-mock && npm run css:watch
