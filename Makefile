# ==============================================================================
# Silvasonic Makefile
# ==============================================================================

# Definiert die Standard-Shell für Make (sorgt für konsistentes Verhalten)
SHELL := /bin/bash

# Wenn man nur `make` eintippt, wird standardmäßig `help` aufgerufen
.DEFAULT_GOAL := help

# ==============================================================================
# CORE VARIABLES
# ==============================================================================
# System Python for bootstrapping (before .venv exists)
BOOTSTRAP_PYTHON = python3
# Isolated Python (guarantees execution within the uv virtual environment)
VENV_PYTHON = uv run python
# Parallel workers for unit tests (0 = disabled)
PYTEST_WORKERS = 4

# .env is loaded by the Python scripts (scripts/compose.py)

# ==============================================================================
# TARGETS
# ==============================================================================

.PHONY: help init build start stop restart logs clear clean nuke fix check check-full test-unit test-int test-smoke test-all

help: ## 🛟  Zeigt diese Hilfe an (Self-Documenting)
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: ## 🛠️  Initialisiert das Projekt (uv sync, hooks, workspace)
	@$(BOOTSTRAP_PYTHON) scripts/init.py


# ==============================================================================
# CONTAINER LIFECYCLE (Podman / Docker)
# ==============================================================================

build: ## 🔨 Baut die Container-Images
	@$(BOOTSTRAP_PYTHON) scripts/build.py

start: ## 🚀 Startet die Silvasonic Services
	@$(BOOTSTRAP_PYTHON) scripts/start.py

stop: ## 🛑 Stoppt alle Silvasonic Services
	@$(BOOTSTRAP_PYTHON) scripts/stop.py

restart: stop start ## 🔄 Stoppt und startet die Services neu

logs: ## 📜 Zeigt die aggregierten Logs aller Services an
	@$(BOOTSTRAP_PYTHON) scripts/logs.py

reset: stop clean init build start ## 🧨 Factory Reset (Stoppen, Clean, Init, Build, Start)


# ==============================================================================
# CODE QUALITY
# ==============================================================================

fix: ## 🔧 Führt Auto-Fixer aus (Ruff Format, Lint Fixes)
	@$(VENV_PYTHON) scripts/fix.py


check: ## 🔍 Code Quality: Ruff, Mypy, Unit & Integration Tests (Fast)
	@$(VENV_PYTHON) scripts/check.py

check-full: ## 🧬 Full CI Pipeline: Lint → Type → Test → Build → Smoke → Clean
	@$(VENV_PYTHON) scripts/check_full.py


# ==============================================================================
# TESTING (Nutzt direkt Pytest mit deinen neuen Markern!)
# ==============================================================================

test-unit: ## 🧪 Führt schnelle Unit-Tests aus (Mocked, ohne externe Services)
	@uv run pytest -m "unit" -n $(PYTEST_WORKERS) --cov --cov-report=term-missing

test-int: ## 🐢 Führt Integrationstests aus (Testcontainers startet DB automatisch!)
	@uv run pytest -m "integration"

test-smoke: ## 💨 Smoke Tests (⚠️  Stack muss laufen: make start)
	@uv run pytest -m "smoke"

test-all: ## 🏭 Führt alle Tests aus (Unit + Integration, ohne E2E/Smoke)
	@uv run pytest -m "unit or integration"

# ## test-e2e: 🕸️  Führt End-to-End Playwright Tests aus (noch keine Logik)
# test-e2e:
# 	@uv run pytest -m "e2e"


# ==============================================================================
# MAINTENANCE & DOCS
# ==============================================================================

clear: ## 🧹 Räumt Root-Verzeichnis auf und löscht Caches (.keep wird beachtet)
	@$(BOOTSTRAP_PYTHON) scripts/clear.py

clean: ## 🧼 clear + Container-Volumes löschen (Storage-Reset)
	@$(BOOTSTRAP_PYTHON) scripts/clean.py

nuke: clean ## ☢️  clean + .venv + Silvasonic-Images löschen (Full Reset)
	@rm -rf .venv
	@echo "☢️  Venv destroyed."
	@$(BOOTSTRAP_PYTHON) scripts/nuke.py
	@echo "☢️  Full reset done. Run 'make init' to rebuild."


# ## docs: 📚 Startet den lokalen MkDocs Server inkl. Live-Reload
# docs:
# 	@echo "Starting docs server on http://localhost:8085..."
# 	@uv run mkdocs serve -a localhost:8085

# ## openapi: 🗺️  Generiert die OpenAPI/Swagger JSON Datei aus dem FastAPI Code
# openapi:
# 	@$(VENV_PYTHON) scripts/generate_openapi.py