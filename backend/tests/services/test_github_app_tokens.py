"""Unit tests for GitHub App JWT + installation token exchange."""

from unittest.mock import MagicMock, patch

import pytest

from app.services import github_app_tokens
from app.services.github_app_tokens import (
    GithubAppTokenError,
    create_github_app_jwt,
    mint_installation_access_token,
)


def _settings_with_pem() -> MagicMock:
    s = MagicMock()
    s.GITHUB_APP_ID = "123456"
    s.GITHUB_APP_PRIVATE_KEY = (
        "-----BEGIN RSA PRIVATE KEY-----\nTEST\n-----END RSA PRIVATE KEY-----"
    )
    return s


def test_create_github_app_jwt_requires_credentials() -> None:
    s = MagicMock()
    s.GITHUB_APP_ID = None
    s.GITHUB_APP_PRIVATE_KEY = None
    with pytest.raises(GithubAppTokenError):
        create_github_app_jwt(settings=s)


def test_create_github_app_jwt_payload_uses_app_id_as_iss() -> None:
    settings = _settings_with_pem()
    with patch.object(
        github_app_tokens.jwt, "encode", return_value="header.payload.sig"
    ) as enc:
        create_github_app_jwt(settings=settings, ttl_seconds=90)
    payload = enc.call_args[0][0]
    assert payload["iss"] == "123456"
    assert enc.call_args[1]["algorithm"] == "RS256"


def test_create_github_app_jwt_raises_github_app_token_error_when_rs256_missing() -> (
    None
):
    settings = _settings_with_pem()
    with patch.object(
        github_app_tokens.jwt,
        "encode",
        side_effect=NotImplementedError(
            "Algorithm 'RS256' could not be found. Do you have cryptography installed?"
        ),
    ):
        with pytest.raises(GithubAppTokenError, match="cryptography"):
            create_github_app_jwt(settings=settings)


def test_mint_installation_access_token_parses_response() -> None:
    settings = _settings_with_pem()
    fake_response = MagicMock()
    fake_response.status_code = 201
    fake_response.json.return_value = {
        "token": "repo-token",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(github_app_tokens.jwt, "encode", return_value="app.jwt"),
        patch("app.services.github_app_tokens.httpx.Client", return_value=fake_client),
    ):
        out = mint_installation_access_token(settings=settings, installation_id=42)

    assert out.token == "repo-token"
    assert out.expires_at == "2099-01-01T00:00:00Z"
    called_url = fake_client.post.call_args[0][0]
    assert called_url.endswith("/app/installations/42/access_tokens")
