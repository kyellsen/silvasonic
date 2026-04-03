"""Unit tests for silvasonic.core.crypto — Fernet encryption helpers.

Covers encrypt/decrypt roundtrip, plaintext fallback, wrong key handling,
missing env var, and key generation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken
from silvasonic.core.crypto import (
    decrypt_value,
    encrypt_value,
    generate_key,
    load_encryption_key,
)


@pytest.mark.unit
class TestCrypto:
    """Tests for the crypto module."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """decrypt_value(encrypt_value(s, k), k) == s."""
        key = Fernet.generate_key()
        plaintext = "my-secret-password-123"

        encrypted = encrypt_value(plaintext, key)
        assert encrypted.startswith("enc:")
        assert encrypted != plaintext

        decrypted = decrypt_value(encrypted, key)
        assert decrypted == plaintext

    def test_plaintext_fallback(self) -> None:
        """No enc: prefix → returned as-is."""
        key = Fernet.generate_key()
        plain = "already-plain-value"

        result = decrypt_value(plain, key)
        assert result == plain

    def test_decrypt_wrong_key_fails(self) -> None:
        """Wrong key → InvalidToken raised."""
        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()

        encrypted = encrypt_value("secret", key1)

        with pytest.raises(InvalidToken):
            decrypt_value(encrypted, key2)

    def test_load_encryption_key_missing(self) -> None:
        """Env var not set → clear error message."""
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(RuntimeError, match="SILVASONIC_ENCRYPTION_KEY"),
        ):
            load_encryption_key()

    def test_generate_key_valid_fernet(self) -> None:
        """Generated key is valid Fernet key."""
        key_str = generate_key()
        # Should not raise — valid Fernet key
        f = Fernet(key_str.encode("utf-8"))
        # Verify it can encrypt/decrypt
        token = f.encrypt(b"test")
        assert f.decrypt(token) == b"test"
