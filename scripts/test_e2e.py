#!/usr/bin/env python3
from common import print_header, print_success, run_command


def main() -> None:
    """Run E2E tests (Browser/Playwright)."""
    print_header("Running E2E Tests (Browser)...")
    # We target the tests/e2e folder specifically to be safe,
    # but we could also use -m e2e if markers are strictly used.
    # Targeting the folder ensures we only run what is intended for e2e.
    run_command(["uv", "run", "pytest", "tests/e2e", "--cov=.", "--cov-report=term-missing"])
    print_success("E2E tests passed.")


if __name__ == "__main__":
    main()
