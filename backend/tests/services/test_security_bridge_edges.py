"""Edge cases for OAuth bridge token helpers."""

from unittest.mock import patch

import jwt
import pytest

from app.core.security import create_bridge_token, verify_bridge_token


def test_verify_bridge_token_requires_secret() -> None:
    with patch("app.core.security.settings") as s:
        s.GITHUB_BRIDGE_SECRET = None
        s.GITHUB_BRIDGE_AUDIENCE = "fastapi-bridge"
        s.GITHUB_BRIDGE_ISSUER = "authjs"
        with pytest.raises(jwt.InvalidTokenError):
            verify_bridge_token("any")


def test_create_bridge_token_requires_secret() -> None:
    with patch("app.core.security.settings") as s:
        s.GITHUB_BRIDGE_SECRET = None
        s.GITHUB_BRIDGE_ISSUER = "authjs"
        s.GITHUB_BRIDGE_AUDIENCE = "fastapi-bridge"
        with pytest.raises(RuntimeError):
            create_bridge_token(provider_account_id="1")
