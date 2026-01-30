#!/bin/bash
set -e

echo "🔧 Running Auto-Fixes..."

# 1. Format code (Black/Isort equivalent via Ruff)
uv run ruff format .

# 2. Fix linting errors (unused imports, etc.)
uv run ruff check --fix .

echo "✅ Fix complete."