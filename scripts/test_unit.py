#!/usr/bin/env python3
from common import print_header, print_success, run_command


def main() -> None:
    """Run unit tests (excluding integration tests)."""
    print_header("Running Unit Tests (Skipping Integration)...")
    run_command(
        ["uv", "run", "pytest", "-m", "not integration", "--cov=.", "--cov-report=term-missing"]
    )
    print_success("Unit tests passed.")


if __name__ == "__main__":
    main()
