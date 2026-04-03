import pytest


@pytest.mark.e2e
def test_placeholder() -> None:
    """Placeholder test because pytest returns exit code 5 (failure) if no tests are collected.

    E2E tests are planned for v0.9.0+.
    """
    pass
