"""
AgentZline Security Utilities.

Fernet-based encryption for the token vault.
All Meta/WhatsApp tokens are encrypted at rest before database storage.
"""

import hashlib
import hmac
import secrets
import uuid
from functools import lru_cache

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

# NOTE: get_db imported lazily inside functions to avoid engine init side-effects
# during config-only contexts, but there is no circular import (database -> config only).


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


def generate_tenant_api_key() -> tuple[str, str]:
    """Generate a raw tenant API key and its SHA-256 hex digest.

    Returns:
        Tuple of (raw_key, key_hash). Store only the hash; return raw once.
    """
    raw = "azl_" + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


def hash_api_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def verify_api_key_dependency(
    request: Request, db: AsyncSession = Depends(get_db)
) -> uuid.UUID | None:
    """FastAPI dependency enforcing X-API-Key / Bearer auth with tenant isolation.

    - If ADMIN_API_KEY configured and matches (constant-time), grants admin access (returns None).
    - If APP_ENV in development/test and ADMIN_API_KEY empty, allows unauthenticated access.
    - Otherwise hashes incoming key and matches Tenant.api_key_hash.

    Use as `auth: Any = Depends(verify_api_key_dependency)` alongside
    `db: AsyncSession = Depends(get_db)`; call `enforce_tenant_access(request, tenant_id)`
    in the route body to block cross-tenant access.
    """

    settings = get_settings()
    # Extract key from header
    incoming: str | None = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if not incoming:
        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            incoming = auth[7:].strip()

    # Admin bypass
    admin_key = settings.ADMIN_API_KEY or ""
    if incoming and admin_key and hmac.compare_digest(incoming, admin_key):
        request.state.authenticated_tenant_id = None
        request.state.is_admin = True
        return None

    # Dev/test open mode when no admin key configured
    if settings.APP_ENV.lower() in ("development", "test") and not admin_key:
        # Still try to attach tenant if key provided and db available
        request.state.is_admin = False
        if not incoming or db is None:
            request.state.authenticated_tenant_id = None
            return None
        # Fall through to tenant lookup if a key was supplied
    else:
        request.state.is_admin = False
        if not incoming:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key. Provide X-API-Key header or Authorization: Bearer token.",
            )

    if incoming is None:
        request.state.authenticated_tenant_id = None
        # Dev/test open mode handled below; strict mode raises
        if settings.APP_ENV.lower() in ("development", "test") and not admin_key:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header or Authorization: Bearer token.",
        )

    from app.models.tenant import Tenant

    digest = hash_api_key(incoming)
    res = await db.execute(select(Tenant).where(Tenant.api_key_hash == digest))
    tenant = res.scalars().first()
    if tenant is None:
        # In dev/test open mode without admin key, allow unauthenticated pass-through
        if settings.APP_ENV.lower() in ("development", "test") and not admin_key:
            request.state.authenticated_tenant_id = None
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    request.state.authenticated_tenant_id = tenant.id
    return tenant.id


def enforce_tenant_access(request: Request, tenant_id: uuid.UUID | str | None) -> None:
    """Raise 403 if authenticated tenant does not match the requested tenant_id.

    Admin (authenticated_tenant_id is None + is_admin) can access any tenant.
    Unauthenticated dev/test requests (None, not admin) are allowed through.
    """
    is_admin = getattr(request.state, "is_admin", False)
    auth_tid = getattr(request.state, "authenticated_tenant_id", None)
    if is_admin or auth_tid is None:
        return
    if tenant_id is None:
        return
    try:
        requested = uuid.UUID(str(tenant_id)) if not isinstance(tenant_id, uuid.UUID) else tenant_id
    except ValueError:
        return
    if requested != auth_tid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: tenant isolation — cannot access another tenant's resources.",
        )
