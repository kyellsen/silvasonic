#!/bin/bash
set -e

echo "🚀 Starting Silvasonic Stack (Rootless)..."

# Config Check
if [ ! -f .env ]; then
  echo "⚠️ .env not found. Copying from .env.example..."
  cp .env.example .env
fi

# Auto-Provisioning: Ensure directories exist
# We use python to parse the compose file rather than fragile bash regex
echo "📂 Verifying storage directories..."

python3 -c '
import yaml
import os
import sys

try:
    with open("podman-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    workspace_path = os.environ.get("SILVASONIC_WORKSPACE_PATH", "./workspace")
    workspace_path = os.path.abspath(workspace_path)

    print(f"   Target Workspace: {workspace_path}")

    if not os.path.exists(workspace_path):
        os.makedirs(workspace_path, exist_ok=True)

    services = compose.get("services", {})
    for name, service in services.items():
        volumes = service.get("volumes", [])
        for vol in volumes:
            if isinstance(vol, str):
                # Format: host_path:container_path[:options]
                host_path = vol.split(":")[0]

                # Resolve variable expansion strictly for workspace path
                if "${SILVASONIC_WORKSPACE_PATH:-./workspace}" in host_path:
                    host_path = host_path.replace("${SILVASONIC_WORKSPACE_PATH:-./workspace}", workspace_path)
                elif "./workspace" in host_path: # Fallback
                     host_path = host_path.replace("./workspace", workspace_path)

                # Normalize and check if it is within workspace (securityish) or just create it
                # We simply create it if it looks like a directory mount
                if not os.path.splitext(host_path)[1]: # Crude check: no extension = directory
                    try:
                        os.makedirs(host_path, exist_ok=True)
                        # Set permissions to conservative 755 (owner writable, others readable)
                        # We let podman keep-id handle ownership mapping
                        os.chmod(host_path, 0o755)
                        print(f"   Confirmed: {host_path}")
                    except Exception as e:
                        print(f"   Error creating {host_path}: {e}")

except Exception as e:
    print(f"❌ Error parsing compose file: {e}")
    sys.exit(1)
'

# Start Podman (Rootless, Detached)
podman-compose --in-pod false up --build -d

echo "✅ Stack started in background."
echo "📜 View logs with: make logs"