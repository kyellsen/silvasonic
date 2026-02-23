"""Security utilities for encryption and secret management."""

import base64
import os

import structlog
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = structlog.get_logger()


def get_app_secret() -> str:
    """Retrieve the application secret from environment or warn."""
    secret = os.getenv("SILVASONIC_APP_SECRET")
    if not secret:
        logger.warning(
            "app_secret_not_set",
            hint="Using insecure default. Set SILVASONIC_APP_SECRET in production!",
        )
        return "dev-unsafe-default-secret-do-not-use-in-prod"
    return secret


def _derive_key(secret: str, salt: bytes = b"silvasonic_static_salt") -> bytes:
    """Derive a URL-safe base64-encoded 32-byte key from the secret."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def encrypt_string(plaintext: str) -> str:
    """Encrypt a string using the app secret."""
    if not plaintext:
        return ""

    key = _derive_key(get_app_secret())
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_string(ciphertext: str) -> str:
    """Decrypt a string using the app secret."""
    if not ciphertext:
        return ""

    try:
        key = _derive_key(get_app_secret())
        f = Fernet(key)
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        raise ValueError("Decryption failed. Invalid Secret or Corrupted Data.") from None
