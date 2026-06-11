"""
AgentZline Security Utilities.

Fernet-based encryption for the token vault.
All Meta/WhatsApp tokens are encrypted at rest before database storage.
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _get_fernet() -> Fernet:
    """Lazily initialize Fernet cipher — avoids crash with placeholder keys."""
    settings = get_settings()
    return Fernet(settings.FERNET_ENCRYPTION_KEY.encode())


def encrypt_token(plaintext: str) -> str:
    """
    Encrypt a plaintext API token for database storage.

    Args:
        plaintext: The raw token string to encrypt.

    Returns:
        Base64-encoded encrypted string.
    """
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """
    Decrypt an encrypted token from the database.

    Args:
        encrypted: The Base64-encoded encrypted token string.

    Returns:
        The original plaintext token string.
    """
    return _get_fernet().decrypt(encrypted.encode()).decode()
