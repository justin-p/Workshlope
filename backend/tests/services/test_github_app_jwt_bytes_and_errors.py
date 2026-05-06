"""Branches in github_app_tokens (bytes JWT + HTTP error bodies)."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.github_app_tokens import (
    GithubAppTokenError,
    mint_installation_access_token,
)


def _settings() -> MagicMock:
    s = MagicMock()
    s.GITHUB_APP_ID = "99"
    s.GITHUB_APP_PRIVATE_KEY = (
        "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----"
    )
    return s


def test_create_github_app_jwt_decodes_when_encode_returns_bytes() -> None:
    settings = _settings()
    with patch(
        "app.services.github_app_tokens.jwt.encode",
        return_value=b"raw-bytes",
    ):
        from app.services.github_app_tokens import create_github_app_jwt

        out = create_github_app_jwt(settings=settings)
        assert out == "raw-bytes"


def test_mint_raises_on_non_201_response() -> None:
    settings = _settings()
    resp = MagicMock()
    resp.status_code = 502
    resp.text = "bad gateway"
    fake_client = MagicMock()
    fake_client.post.return_value = resp
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.services.github_app_tokens.jwt.encode", return_value="jwt"),
        patch(
            "app.services.github_app_tokens.httpx.Client",
            return_value=fake_client,
        ),
    ):
        with pytest.raises(GithubAppTokenError, match="502"):
            mint_installation_access_token(settings=settings, installation_id=9)


def test_mint_raises_when_response_missing_token_string() -> None:
    settings = _settings()
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {"expires_at": None}
    fake_client = MagicMock()
    fake_client.post.return_value = resp
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.services.github_app_tokens.jwt.encode", return_value="jwt"),
        patch(
            "app.services.github_app_tokens.httpx.Client",
            return_value=fake_client,
        ),
    ):
        with pytest.raises(GithubAppTokenError, match="missing token"):
            mint_installation_access_token(settings=settings, installation_id=9)
