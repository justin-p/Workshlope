from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.core.config import Settings


class GithubAppTokenError(RuntimeError):
    """Raised when JWT creation or installation token exchange fails."""


def create_github_app_jwt(*, settings: Settings, ttl_seconds: int = 60) -> str:
    """Sign a short-lived GitHub App JWT (RS256) for App API calls."""
    if not settings.GITHUB_APP_ID or not settings.GITHUB_APP_PRIVATE_KEY:
        raise GithubAppTokenError(
            "GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY are not configured"
        )
    now = int(time.time())
    pem = settings.GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n")
    payload: dict[str, Any] = {
        "iat": now - 60,
        "exp": now + ttl_seconds,
        "iss": settings.GITHUB_APP_ID,
    }
    encoded = jwt.encode(payload, pem, algorithm="RS256")
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8")
    return encoded


@dataclass(frozen=True)
class InstallationAccessToken:
    token: str
    expires_at: str | None


def mint_installation_access_token(
    *, settings: Settings, installation_id: int
) -> InstallationAccessToken:
    """POST /app/installations/{id}/access_tokens → repository-scoped token."""
    app_token = create_github_app_jwt(settings=settings)
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers)
    if response.status_code != 201:
        raise GithubAppTokenError(
            f"GitHub installation token request failed "
            f"({response.status_code}): {response.text}",
        )
    data = response.json()
    tok = data.get("token")
    if not isinstance(tok, str):
        raise GithubAppTokenError("GitHub installation token response missing token")
    expires_at = (
        data.get("expires_at") if isinstance(data.get("expires_at"), str) else None
    )
    return InstallationAccessToken(token=tok, expires_at=expires_at)
