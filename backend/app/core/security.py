from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def verify_bridge_token(token: str) -> dict[str, Any]:
    """Verify a signed bridge token issued by the Auth.js service.

    Validates signature, audience, and expiry. Raises jwt.InvalidTokenError on any
    failure (caller should map to HTTP 401).
    """
    if not settings.GITHUB_BRIDGE_SECRET:
        raise jwt.InvalidTokenError("GITHUB_BRIDGE_SECRET is not configured")
    return jwt.decode(
        token,
        settings.GITHUB_BRIDGE_SECRET,
        algorithms=[ALGORITHM],
        audience=settings.GITHUB_BRIDGE_AUDIENCE,
        issuer=settings.GITHUB_BRIDGE_ISSUER,
    )


def create_bridge_token(
    *,
    provider: str = "github",
    provider_account_id: str,
    provider_login: str | None = None,
    email: str | None = None,
    name: str | None = None,
    full_name: str | None = None,
    avatar_url: str | None = None,
    picture: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed bridge token. Used by the Auth.js service and tests.

    Production Auth.js service uses the same shared secret (HS256) to sign.
    """
    if not settings.GITHUB_BRIDGE_SECRET:
        raise RuntimeError("GITHUB_BRIDGE_SECRET is not configured")
    expires_delta = expires_delta or timedelta(minutes=5)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "iss": settings.GITHUB_BRIDGE_ISSUER,
        "aud": settings.GITHUB_BRIDGE_AUDIENCE,
        "iat": now,
        "exp": now + expires_delta,
        "provider": provider,
        "provider_account_id": str(provider_account_id),
    }
    if provider_login is not None:
        payload["provider_login"] = provider_login
    if email is not None:
        payload["email"] = email
    if name is not None:
        payload["name"] = name
    if full_name is not None:
        payload["full_name"] = full_name
    if avatar_url is not None:
        payload["avatar_url"] = avatar_url
    if picture is not None:
        payload["picture"] = picture
    return jwt.encode(payload, settings.GITHUB_BRIDGE_SECRET, algorithm=ALGORITHM)
