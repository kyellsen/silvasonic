#!/usr/bin/env python3
import os
import re
import shutil

import yaml
from common import print_error, print_header, print_step, print_success, print_warning, run_command


def load_env_file(filepath: str = ".env") -> None:
    """Load .env file into os.environ."""
    if not os.path.exists(filepath):
        return

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Handle key=value
            if "=" in line:
                key, value = line.split("=", 1)
                # Remove quotes if present
                value = value.strip("'\"")
                os.environ[key] = value


def resolve_variable(match: re.Match[str], env_vars: dict[str, str]) -> str:
    """Callback for regex to resolve ${VAR} or ${VAR:-default}."""
    content = match.group(1) or match.group(2)  # Group 1 is ${...}, Group 2 is $VAR

    if not content:
        return match.group(0)  # Should not match?

    # Check for default value syntax :-
    key = content
    default = ""

    if ":-" in content:
        key, default = content.split(":-", 1)
        # Handle case where default contains } at end (from regex group capture if simple)
        # But our regex should handle it.

    return env_vars.get(key, default)


def main() -> None:
    """Start the Silvasonic stack in rootless mode."""
    print_header("Starting Silvasonic Stack (Rootless)...")

    # 1. Config Check
    if not os.path.exists(".env"):
        print_warning(".env not found. Copying from .env.example...")
        shutil.copy(".env.example", ".env")

    # 2. Load Environment Variables
    load_env_file(".env")

    # 3. Auto-Provisioning
    print_step("Verifying storage directories...")

    try:
        with open("podman-compose.yml") as f:
            compose = yaml.safe_load(f)

        workspace_path = os.environ.get("SILVASONIC_WORKSPACE_PATH", "./workspace")
        workspace_path = os.path.abspath(workspace_path)
        print(f"   Target Workspace: {workspace_path}")

        if not os.path.exists(workspace_path):
            os.makedirs(workspace_path, exist_ok=True)

        services = compose.get("services", {})
        for _, service in services.items():
            volumes = service.get("volumes", [])
            for vol in volumes:
                if isinstance(vol, str):
                    # FIX: Perform substitution BEFORE splitting, because ${VAR:-default} contains a colon!
                    pattern = (
                        r"\$\{SILVASONIC_WORKSPACE_PATH(?::-[^}]*)?\}|\$SILVASONIC_WORKSPACE_PATH"
                    )

                    # Substitute in the full volume string
                    resolved_vol = re.sub(pattern, workspace_path, vol)

                    # Also handle fallback ./workspace if variable was not used but literal path was
                    if "./workspace" in resolved_vol:
                        resolved_vol = resolved_vol.replace("./workspace", workspace_path)

                    # NOW we can safely split, as resolved path shouldn't have conflicting colons
                    # (unless windows, but we are linux)
                    host_path = resolved_vol.split(":")[0]

                    # Check extension (naive check for directory vs file mount)
                    if not os.path.splitext(host_path)[1]:
                        try:
                            # print(f"Creating {host_path}")
                            os.makedirs(host_path, exist_ok=True)
                            os.chmod(host_path, 0o755)
                        except Exception as e:
                            print_warning(f"Could not create {host_path}: {e}")

    except Exception as e:
        print_error(f"Error parsing podman-compose.yml: {e}")
        # We don't exit here, we try to proceed, letting podman complain if mounts missing

    # 4. Start Podman
    print_step("Running podman-compose up...")
    run_command(["podman-compose", "--in-pod", "false", "up", "--build", "-d"], env=os.environ)

    print_success("Stack started in background.")
    print("📜 View logs with: make logs")


if __name__ == "__main__":
    main()
