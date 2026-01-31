"""Tests for the template service."""

from silvasonic.template.main import hello_world


def test_hello_world() -> None:
    """Test that the hello_world function returns the expected string."""
    assert hello_world() == "Hello from Silvasonic Template Service!"
