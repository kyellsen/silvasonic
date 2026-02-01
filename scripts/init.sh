#!/bin/bash
set -e

echo "🛠️ Initializing Silvasonic Development Environment..."

# 1. Python Dependencies
echo "📦 Syncing dependencies..."
uv sync

# 2. Git Hooks
echo "🪝 Installing Pre-Commit Hooks..."
uv run pre-commit install --hook-type pre-commit --hook-type pre-push

# 3. Workspace Structure (Strict Adherence to filesystem_governance.md)
echo "📂 Enforcing Workspace Structure..."
WORKSPACE_DIR="${SILVASONIC_WORKSPACE_PATH:-/mnt/data/dev_workspaces/silvasonic}"

# Helper function for directory creation
ensure_dir() {
  local path="$1"
  if [ ! -d "$path" ]; then
    echo "   Creating: $path"
    mkdir -p "$path"
  fi
}

# Core Infrastructure
ensure_dir "${WORKSPACE_DIR}/database"
ensure_dir "${WORKSPACE_DIR}/redis"
ensure_dir "${WORKSPACE_DIR}/gateway/logs"
ensure_dir "${WORKSPACE_DIR}/web-interface/logs"
ensure_dir "${WORKSPACE_DIR}/monitor/logs"
ensure_dir "${WORKSPACE_DIR}/controller/logs"

# Recorder (The "Micro")
ensure_dir "${WORKSPACE_DIR}/recorder/recordings/raw"
ensure_dir "${WORKSPACE_DIR}/recorder/recordings/processed"
ensure_dir "${WORKSPACE_DIR}/recorder/logs"

# Processor (The Data Manager)
ensure_dir "${WORKSPACE_DIR}/processor/artifacts"
ensure_dir "${WORKSPACE_DIR}/processor/logs"

# Uploader
ensure_dir "${WORKSPACE_DIR}/uploader/buffer"
ensure_dir "${WORKSPACE_DIR}/uploader/logs"

# Optional/Inference Services
ensure_dir "${WORKSPACE_DIR}/birdnet/logs"
ensure_dir "${WORKSPACE_DIR}/batdetect/logs"
ensure_dir "${WORKSPACE_DIR}/weather/logs"

# 4. Executable Permissions
echo "🔐 Setting script permissions..."
chmod +x scripts/*.sh

# 5. Workspace Permissions
echo "🔐 Enforcing Workspace Permissions (755)..."
# Ensure the host user owns the workspace and it's writable
chmod -R 755 "${WORKSPACE_DIR}"

# 6. Hardware Access Verify (Controller & Micro)
echo "🔍 Verifying Hardware Access Groups..."
REQUIRED_GROUPS=("audio" "gpio" "spi" "i2c" "dialout")
MISSING_GROUPS=()

for group in "${REQUIRED_GROUPS[@]}"; do
  if groups | grep -q "\b$group\b"; then
    echo "   ✅ User is in '$group'"
  else
    echo "   ⚠️  WARNING: User is NOT in '$group' group. Hardware access (Mic/HATs) may fail."
    MISSING_GROUPS+=("$group")
  fi
done

if [ ${#MISSING_GROUPS[@]} -ne 0 ]; then
  echo "   ❌ PLEASE FIX: Create groups or add user: sudo usermod -aG ${MISSING_GROUPS[*]} \$USER"
  # We don't exit 1 here to allow dev work without hardware, but typical install should have it.
fi

echo "✅ Initialization complete."