#!/bin/bash
set -e

echo "🔍 Starting Deep Verification (Check)..."

# 1. Static Analysis (Linter without fixing)
echo "🧐 Running Linter (Ruff)..."
uv run ruff check .

# 2. Type Checking (Mypy)
echo "🧠 Running Type Checker (Mypy)..."
uv run mypy .

# 3. Unit Tests (Pytest)
echo "🧪 Running Tests..."
# Führt Tests aus, generiert Coverage-Report, bricht bei Fehler ab
uv run pytest --cov=. --cov-report=term-missing

echo "✅ All checks passed! Ready to push."