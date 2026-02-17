#!/usr/bin/env python3
"""Start all Silvasonic services in detached mode via compose."""

from pathlib import Path

import init
from common import print_header, print_success, print_warning
from compose import compose


def main() -> None:
    """Start all Silvasonic services."""
    # Check if .venv exists
    project_root = Path(__file__).resolve().parent.parent
    venv_path = project_root / ".venv"

    if not venv_path.exists():
        print_warning("Virtual environment (.venv) not found!")
        print_warning("Automatically running 'make init' to bootstrap the project...")
        init.main()
        print_success("Initialization complete. Proceeding with startup...")

    print_header("Starting Silvasonic Services")
    compose("up", "-d")
    print_success("Silvasonic services are running.")


if __name__ == "__main__":
    main()
