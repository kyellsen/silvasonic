"""Fernet encryption helpers for cloud storage credentials (v0.6.0).

Sensitive values (user, pass) in ``system_config`` JSONB are stored with
an ``enc:`` prefix.  The decryption key lives in ``.env`` as
``SILVASONIC_ENCRYPTION_KEY``.

Usage::

    from silvasonic.core.crypto import encrypt_value, decrypt_value, load_encryption_key

    key = load_encryption_key()
    token = encrypt_value("my-password", key)   # "enc:gAAAAAB..."
    plain = decrypt_value(token, key)            # "my-password"
    plain = decrypt_value("already-plain", key)  # "already-plain" (fallback)

Key generation::

    python -m silvasonic.core.crypto generate-key
"""

from __future__ import annotations

import os
import sys

import structlog
from cryptography.fernet import Fernet

log = structlog.get_logger()

_ENC_PREFIX = "enc:"
_ENV_VAR = "SILVASONIC_ENCRYPTION_KEY"


def encrypt_value(plaintext: str, key: bytes) -> str:
    """Fernet-encrypt *plaintext* and return ``enc:<token>`` string."""
    f = Fernet(key)
    token = f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX}{token}"


def decrypt_value(value: str, key: bytes) -> str:
    """Decrypt if ``enc:`` prefix present, otherwise return as-is (plaintext fallback)."""
    if not value.startswith(_ENC_PREFIX):
        return value
    token = value[len(_ENC_PREFIX) :]
    f = Fernet(key)
    return f.decrypt(token.encode("utf-8")).decode("utf-8")


def load_encryption_key() -> bytes:
    """Read ``SILVASONIC_ENCRYPTION_KEY`` from environment.

    Raises:
        RuntimeError: If the environment variable is not set or empty.
    """
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        msg = (
            f"Environment variable {_ENV_VAR} is not set or empty. "
            "Generate one with: python -m silvasonic.core.crypto generate-key"
        )
        raise RuntimeError(msg)
    return raw.encode("utf-8")


def generate_key() -> str:
    """Generate a new Fernet key and return it as a string."""
    return Fernet.generate_key().decode("utf-8")


# ---------------------------------------------------------------------------
# CLI entry point: python -m silvasonic.core.crypto generate-key
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "generate-key":
        print(generate_key())
    else:
        print("Usage: python -m silvasonic.core.crypto generate-key", file=sys.stderr)
        sys.exit(1)
