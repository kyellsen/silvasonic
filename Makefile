.PHONY: help init fix check start stop restart reset logs clean docs build-docs

# Default target: Zeigt Hilfe an
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  init      🛠️  Initialize development environment (install deps, hooks)"
	@echo "  fix       🔧 Run auto-fixers (Ruff, Beautysh, YAML, Jinja)"
	@echo "  check     🔍 Run deep verification (Lint, Types, Tests)"
	@echo "  start     🚀 Start Silvasonic stack (Rootless podman-compose)"
	@echo "  stop      🛑 Stop Silvasonic stack"
	@echo "  restart   🔄 Restart stack (stop && start)"
	@echo "  reset     🧨 Stop, Clean Storage, Init, and Start (Factory Reset)"
	@echo "  logs      📜 View container logs (follow)"
	@echo "  clean     🧹 Cleanup artifacts (caches, pyc, coverage)"
	@echo ""

# 1. Setup & Maintenance
# 1. Setup & Maintenance
init:
	@python3 scripts/init.py

fix:
	@python3 scripts/fix.py

check:
	@python3 scripts/check.py

clean:
	@python3 scripts/clean.py

clean-storage:
	@python3 scripts/clean.py --storage

# 2. Runtime Control
start:
	@uv run python3 scripts/start.py

stop:
	@python3 scripts/stop.py

restart: stop start

reset: stop clean-storage init start

logs:
	@podman-compose logs -f

# 3. Documentation
docs:
	@echo "📚 Starting documentation server at http://localhost:8085..."
	@(sleep 2 && xdg-open http://localhost:8085) & uv run mkdocs serve -a localhost:8085


build-docs:
	@uv run mkdocs build

openapi:
	@uv run python3 scripts/generate_openapi.py

