#!/bin/bash
set -e

echo "🛠️ Initializing Development Environment..."

# 1. Python Dependencies
echo "📦 Syncing dependencies..."
uv sync

# 2. Git Hooks
echo "🪝 Installing Pre-Commit Hooks..."
uv run pre-commit install --hook-type pre-commit --hook-type pre-push

# 3. Executable Permissions
echo "🔐 Setting permissions..."
chmod +x scripts/*.sh

echo "✅ Initialization complete."