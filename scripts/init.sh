#!/bin/bash
set -e

echo "🛠️ Initializing Silvasonic Development Environment..."

# 1. Python Dependencies
echo "📦 Syncing dependencies..."
uv sync

# 2. Git Hooks
echo "🪝 Installing Pre-Commit Hooks..."
uv run pre-commit install --hook-type pre-commit --hook-type pre-push

# 3. Workspace Structure
# Directories are now auto-provisioned by scripts/start.sh based on podman-compose.yml
echo "📂 Workspace root check..."
WORKSPACE_DIR="${SILVASONIC_WORKSPACE_PATH:-/mnt/data/dev_workspaces/silvasonic}"
ensure_dir "${WORKSPACE_DIR}"

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
NOT_CONFIGURED_GROUPS=()
PENDING_GROUPS=()

for group in "${REQUIRED_GROUPS[@]}"; do
  if id -Gn | grep -qw "$group"; then
    echo "   ✅ User is in '$group' (active)"
  elif id -Gn "$USER" | grep -qw "$group"; then
    echo "   🔄 User is in '$group' (database) but NOT active in this shell."
    PENDING_GROUPS+=("$group")
  else
    echo "   ⚠️  WARNING: User is NOT in '$group' group."
    NOT_CONFIGURED_GROUPS+=("$group")
  fi
done

if [ ${#NOT_CONFIGURED_GROUPS[@]} -ne 0 ]; then
  echo "   ❌ PLEASE FIX: Create groups or add user: sudo usermod -aG ${NOT_CONFIGURED_GROUPS[*]} \$USER"
fi

if [ ${#PENDING_GROUPS[@]} -ne 0 ]; then
  echo "   ⏳ PENDING: Groups [${PENDING_GROUPS[*]}] are configured but not active."
  echo "      PLEASE REBOOT or LOG OUT completely to apply these permissions."
fi

echo "✅ Initialization complete."