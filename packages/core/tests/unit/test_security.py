"""Unit tests for silvasonic.core.security module."""

import os
from unittest.mock import patch

import pytest
from silvasonic.core.security import decrypt_string, encrypt_string, get_app_secret


@pytest.mark.unit
class TestSecurity:
    """Tests for the security module (encryption/decryption)."""

    def test_get_app_secret_fallback(self) -> None:
        """Test fallback when no secret is in environment."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_app_secret() == "dev-unsafe-default-secret-do-not-use-in-prod"

    def test_get_app_secret_custom(self) -> None:
        """Test retrieving custom secret from environment."""
        with patch.dict(os.environ, {"SILVASONIC_APP_SECRET": "my-super-secret-key"}, clear=True):
            assert get_app_secret() == "my-super-secret-key"

    def test_encrypt_decrypt_lifecycle(self) -> None:
        """Test encryption and decryption round trip."""
        original = "cloud_password_123!"

        with patch.dict(os.environ, {"SILVASONIC_APP_SECRET": "test-key-123"}, clear=True):
            encrypted = encrypt_string(original)

            assert encrypted != original
            assert len(encrypted) > len(original)

            decrypted = decrypt_string(encrypted)
            assert decrypted == original

    def test_empty_string_handling(self) -> None:
        """Test that empty strings return empty strings."""
        assert encrypt_string("") == ""
        assert decrypt_string("") == ""

    def test_invalid_decryption(self) -> None:
        """Test that decrypting with the wrong key fails."""
        with patch.dict(os.environ, {"SILVASONIC_APP_SECRET": "test-key-123"}, clear=True):
            encrypted = encrypt_string("secret_data")

        # Now try to decrypt with a different key
        with (
            patch.dict(os.environ, {"SILVASONIC_APP_SECRET": "wrong-key"}, clear=True),
            pytest.raises(ValueError, match="Decryption failed"),
        ):
            decrypt_string(encrypted)

    def test_corrupted_data_decryption(self) -> None:
        """Test that decrypting non-fernet data fails."""
        with (
            patch.dict(os.environ, {"SILVASONIC_APP_SECRET": "test-key-123"}, clear=True),
            pytest.raises(ValueError, match="Decryption failed"),
        ):
            decrypt_string("not-a-valid-fernet-token")
