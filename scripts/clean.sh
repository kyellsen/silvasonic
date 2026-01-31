#!/bin/bash
set -e

echo "🧹 Cleaning up artifacts..."

# Remove Virtual Environment
# rm -rf .venv  <-- Optional: Kommentiere dies ein, wenn du wirklich ALLES löschen willst

# Caches & Coverage
rm -rf .pytest_cache
rm -rf .mypy_cache
rm -rf htmlcov
rm -f .coverage
rm -f coverage.xml

# Python Bytecode (rekursiv)
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
find . -type d -name "*.egg-info" -exec rm -rf {} +
find . -type d -name ".ruff_cache" -exec rm -rf {} +

# Clean up AI Agent artifacts (root directory only)
# Matches files like fix_debug.txt, grep_output.txt etc.
find . -maxdepth 1 -type f -regextype posix-extended \
  -regex '\./.*(fix|debug|output|grep|check).*\.(txt|log)' \
  -print0 | xargs -0r rm -v

echo "✨ Clean complete."