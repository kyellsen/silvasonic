#!/usr/bin/env python3
from common import print_header, print_success, run_command


def main() -> None:
    """Run integration tests (marked with @integration)."""
    print_header("Running Integration Tests (Slow)...")
    run_command(
        ["uv", "run", "pytest", "-m", "integration", "--cov=.", "--cov-report=term-missing"]
    )
    print_success("Integration tests passed.")


if __name__ == "__main__":
    main()
