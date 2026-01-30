.PHONY: help init fix check start stop restart logs clean

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
	@echo "  logs      📜 View container logs (follow)"
	@echo "  clean     🧹 Cleanup artifacts (caches, pyc, coverage)"
	@echo ""

# 1. Setup & Maintenance
init:
	@./scripts/init.sh

fix:
	@./scripts/fix.sh

check:
	@./scripts/check.sh

clean:
	@./scripts/clean.sh

# 2. Runtime Control
start:
	@./scripts/start.sh

stop:
	@./scripts/stop.sh

restart: stop start

logs:
	@podman-compose logs -f

# 3. Documentation
docs:
	@uv run mkdocs serve

build-docs:
	@uv run mkdocs build

