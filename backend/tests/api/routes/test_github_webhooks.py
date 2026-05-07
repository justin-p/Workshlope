"""GitHub App installation webhook ingestion."""

import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.models import GithubAppInstallation


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_github_webhooks_returns_503_without_secret(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", None, raising=False)
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=b'{"zen":"upstream"}',
    )
    assert response.status_code == 503


def test_github_webhooks_ping(monkeypatch, client: TestClient) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)

    raw = b"{}"
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


def test_github_webhooks_installation_created(monkeypatch, client: TestClient) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)

    installation_id = 42_424_242
    payload = {
        "action": "created",
        "installation": {
            "id": installation_id,
            "target_type": "User",
            "repository_selection": "all",
            "app_slug": "lesson-bot",
            "account": {
                "id": 123,
                "login": "trainer",
                "type": "User",
            },
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "X-GitHub-Event": "installation",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200

    with Session(engine) as session:
        row = session.exec(
            select(GithubAppInstallation).where(
                GithubAppInstallation.id == installation_id
            ),
        ).first()
    assert row is not None
    assert row.account_login == "trainer"
    assert row.app_slug == "lesson-bot"
