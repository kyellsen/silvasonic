"""E2E test placeholder — Playwright browser tests.

This file serves as a minimal placeholder for future end-to-end tests.
Once a frontend or web UI exists, add real browser-based tests here.

Usage:
    just test-e2e
    pytest -m e2e
"""

import pytest


@pytest.mark.e2e
class TestE2EPlaceholder:
    """Placeholder for future Playwright browser tests."""

    def test_e2e_placeholder_passes(self) -> None:
        """Minimal placeholder — always passes.

        Replace this with real browser tests once a web UI is available.

        Example:
            def test_login_flow(self, page: Page) -> None:
                page.goto("http://localhost:8080")
                page.fill("#username", "admin")
                page.click("button[type=submit]")
                expect(page.locator("h1")).to_have_text("Dashboard")
        """
