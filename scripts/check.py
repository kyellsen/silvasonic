#!/usr/bin/env python3
from common import print_header, print_step, print_success, run_command


def main() -> None:
    """Run all verification checks (Lint, Type, Test)."""
    print_header("Starting Deep Verification (Check)...")

    # 1. Static Analysis
    print_step("Running Linter (Ruff)...")
    run_command(["uv", "run", "ruff", "check", "."])

    # 2. Type Checking
    print_step("Running Type Checker (Mypy)...")
    run_command(["uv", "run", "mypy", "."])

    # 3. Unit Tests
    print_step("Running Unit Tests (Fast)...")
    run_command(
        [
            "uv",
            "run",
            "pytest",
            "-m",
            "not integration",
            "--ignore=tests/e2e",
            "--ignore-glob=**/integration/**",
            "--cov=.",
            "--cov-report=term-missing",
        ]
    )

    print_success("All checks passed! Ready to push.")


if __name__ == "__main__":
    main()
