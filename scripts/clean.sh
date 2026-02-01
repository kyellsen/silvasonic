#!/bin/bash
set -e

echo "🧹 Cleaning up artifacts..."

# Remove Virtual Environment
# rm -rf .venv  <-- Optional: Kommentiere dies ein, wenn du wirklich ALLES löschen willst

# Caches & Coverage
# Simple argument parsing
CLEAN_STORAGE=false
for arg in "$@"; do
  if [ "$arg" == "--storage" ]; then
    CLEAN_STORAGE=true
  fi
done

# Caches & Coverage
rm -rf .pytest_cache
rm -rf .mypy_cache
rm -rf htmlcov
rm -f .coverage
rm -f coverage.xml

# Python Bytecode (recursive)
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
find . -type d -name "*.egg-info" -exec rm -rf {} +
find . -type d -name ".ruff_cache" -exec rm -rf {} +

# Clean up AI Agent artifacts (root directory only)
find . -maxdepth 1 -type f -regextype posix-extended \
  -regex '\./.*(fix|debug|output|grep|check).*\.(txt|log)' \
  -print0 | xargs -0r rm -v

# Factory Reset / Storage Cleanup
if [ "$CLEAN_STORAGE" = true ]; then
  WORKSPACE_DIR="${SILVASONIC_WORKSPACE_PATH:-/mnt/data/dev_workspaces/silvasonic}"
  echo "⚠️  FACTORY RESET: Deleting all persistent data in ${WORKSPACE_DIR}..."
  if [ -d "$WORKSPACE_DIR" ]; then
    rm -rf "${WORKSPACE_DIR}"
    echo "   ✅ Workspace deleted. Run 'make init' to restore structure."
  else
    echo "   ℹ️  Workspace not found, nothing to delete."
  fi
fi

echo "✨ Clean complete."