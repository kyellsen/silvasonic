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
find . -type f -name "*.sh" -print0 | xargs -0 uv run beautysh -i 2

# ---------------------------------------------------------
# 3. YAML (yamlfix)
# ---------------------------------------------------------
echo "📄 Formatting YAML..."
# Ignoriert node_modules oder venv falls vorhanden
uv run yamlfix . --exclude ".venv"

# ---------------------------------------------------------
# 4. HTML / Jinja Templates (djLint)
# ---------------------------------------------------------
echo "🌐 Formatting HTML/Jinja..."
# --reformat = Apply changes
# --indent 2 = Passt zu deinem Tailwind/HTML Style
uv run djlint . --reformat --indent 2 --extension html

echo "✅ Fix complete."