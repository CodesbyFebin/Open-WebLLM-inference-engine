"""Database-backed sessions and per-tenant authorization primitives."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

SESSION_HOURS = 12
INFERENCE_ROLES = {"owner", "admin", "member"}
ADMIN_ROLES = {"owner", "admin"}


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    tenant_id: str | None
    role: str
    auth_kind: str


def password_hash(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def new_session() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    return token, token_hash, expires


def hash_session(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_role(principal: Principal, allowed: set[str]):
    if principal.role not in allowed:
        raise HTTPException(403, "Insufficient role for this operation")


def new_id() -> uuid.UUID:
    return uuid.uuid4()
