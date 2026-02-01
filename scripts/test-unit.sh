#!/bin/bash
set -e

echo "🧪 Running Unit Tests (Skipping Integration)..."

# Führt nur Tests aus, die NICHT mit @pytest.mark.integration markiert sind
# Wir nutzen -m "not integration"
uv run pytest -m "not integration" --cov=. --cov-report=term-missing

echo "✅ Unit tests passed."
