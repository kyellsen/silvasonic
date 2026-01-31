#!/bin/bash
set -e

echo "🔧 Running Auto-Fixes..."

# ---------------------------------------------------------
# 1. Python (Ruff)
# ---------------------------------------------------------
echo "🐍 Formatting Python..."
# Sort imports & standard format
uv run ruff format .
# Fix linting issues (unused imports, etc.)
uv run ruff check --fix .

# ---------------------------------------------------------
# 2. Shell Scripts (Beautysh)
# ---------------------------------------------------------
echo "🐚 Formatting Shell Scripts..."
# Findet alle .sh Dateien und formatiert sie
# -i = indent with 2 spaces (Standard für Google/DevOps)
find . -type f -name "*.sh" -print0 | xargs -0 -r uv run beautysh -i 2

# ---------------------------------------------------------
# 3. YAML (yamlfix)
# ---------------------------------------------------------
echo "📄 Formatting YAML..."
# Find all yaml/yml files, excluding .venv, .git, site, etc.
find . -type f \( -name "*.yaml" -o -name "*.yml" \) \
  -not -path "*/.venv/*" \
  -not -path "*/.git/*" \
  -not -path "*/site/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/.mypy_cache/*" \
  -not -path "*/.ruff_cache/*" \
  -print0 | xargs -0 -r uv run yamlfix

# ---------------------------------------------------------
# 4. HTML / Jinja Templates (djLint)
# ---------------------------------------------------------
echo "🌐 Formatting HTML/Jinja..."
# --reformat = Apply changes
# --indent 2 = Passt zu deinem Tailwind/HTML Style
# Find all html files, excluding .venv, site, etc.
find . -type f -name "*.html" \
  -not -path "*/.venv/*" \
  -not -path "*/.git/*" \
  -not -path "*/site/*" \
  -not -path "*/node_modules/*" \
  -print0 | xargs -0 -r uv run djlint --reformat --indent 2

echo "✅ Fix complete."