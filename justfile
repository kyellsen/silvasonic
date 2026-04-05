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
alias i := init
init:
    @{{ BOOTSTRAP_PYTHON }} scripts/init.py

# ==============================================================================
# CONTAINER LIFECYCLE (Podman)
# ==============================================================================

# 🔨 Baut die Container-Images
alias b := build
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
reset: clean init build start

# ==============================================================================
# CODE QUALITY
# ==============================================================================

# 🔧 Führt Auto-Fixer aus (Ruff Format, Lint Fixes)
fix *args:
    @{{ BOOTSTRAP_PYTHON }} scripts/fix.py {{args}}

# 🔍 Nur Ruff Lint (Read-Only, kein Auto-Fix)
lint:
    @{{ BOOTSTRAP_PYTHON }} scripts/lint.py

# 📈 Prints the repository Lines of Code statistics
linestats:
    @{{ BOOTSTRAP_PYTHON }} scripts/linestats.py

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

# 🎤 Hardware System Tests (Automatisiert, ohne Input-Prompts)
test-hw:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw_auto

# 🔌 Interaktive Hardware System Tests (Manuelles Unplugging an der Konsole)
test-hw-manual:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw_manual

# 🤖 Alle Hardware Tests (Automatisiert + Manuell kombiniert)
test-hw-all:
    @{{ BOOTSTRAP_PYTHON }} scripts/test.py system_hw_all

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
    @uv run mkdocs serve -a 0.0.0.0:8085 --open

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
