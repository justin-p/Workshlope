"""GitHub App installation webhook ingestion."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes.github_webhooks import (
    reset_github_webhook_rate_limiter_for_tests,
    verify_github_signature_sha256,
)
from app.core.config import settings
from app.core.db import engine
from app.models import (
    GithubAppInstallation,
    GithubInstallationRepository,
    GithubWebhookDelivery,
    get_datetime_utc,
)


@pytest.fixture(autouse=True)
def _reset_github_webhook_rate_buckets() -> object:
    reset_github_webhook_rate_limiter_for_tests()
    yield
    reset_github_webhook_rate_limiter_for_tests()


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


@pytest.mark.parametrize(
    "secret,signature,expected",
    [
        ("s", None, False),
        (None, "sha256=ab", False),
        ("s", "sha1=digest", False),
        ("s", "sha256=nope", False),
    ],
)
def test_verify_github_signature_rejects_bad_inputs(
    secret: str | None, signature: str | None, expected: bool
) -> None:
    assert (
        verify_github_signature_sha256(
            body=b"x", secret=secret, signature_header=signature
        )
        is expected
    )


def test_verify_github_signature_accepts_hmac_sha256() -> None:
    body = b'{"installation":{"id":1}}'
    secret = "sekrit"
    assert verify_github_signature_sha256(
        body=body,
        secret=secret,
        signature_header=_sign(body, secret),
    )


def test_github_webhooks_returns_403_on_bad_signature(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    raw = b"{}"
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 403


def test_github_webhooks_installation_unknown_event_returns_ignored(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    raw = b"{}"
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ignored": "push"}


def test_github_webhooks_installation_malformed_json(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    raw = b"not-json{{{"
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "X-GitHub-Event": "installation",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


def test_github_webhooks_installation_no_id_short_circuits_ok(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    payload = {"action": "created", "installation": {}}
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
    assert response.json() == {"ok": True}


def test_github_webhooks_installation_unknown_action(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    installation_id = 55
    payload = {
        "action": "edited",
        "installation": {"id": installation_id, "account": {"id": 1, "login": "z"}},
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
    assert response.json().get("unknown_action") == "edited"


def test_github_webhooks_installation_deleted(monkeypatch, client: TestClient) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    installation_id = 77
    session = Session(engine)
    session.add(
        GithubAppInstallation(
            id=installation_id,
            account_id=1,
            account_login="a",
            account_type="User",
            target_type="User",
            repository_selection="all",
            app_slug=None,
            suspended_at=None,
        ),
    )
    session.commit()
    session.close()

    payload = {"action": "deleted", "installation": {"id": installation_id}}
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

    with Session(engine) as s2:
        assert s2.get(GithubAppInstallation, installation_id) is None


def test_github_webhooks_installation_suspend_resume_cycle(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    installation_id = 88

    payload_create = {
        "action": "created",
        "installation": {
            "id": installation_id,
            "repository_selection": "all",
            "app": {"slug": "lesson-app"},
            "account": {"id": 99, "login": "coach", "type": "User"},
        },
    }
    raw_create = json.dumps(payload_create).encode()
    resp = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw_create,
        headers={
            "X-GitHub-Event": "installation",
            "X-Hub-Signature-256": _sign(raw_create, secret),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200

    raw_suspend = json.dumps(
        {"action": "suspend", "installation": {"id": installation_id}}
    ).encode()
    rsp = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw_suspend,
        headers={
            "X-GitHub-Event": "installation",
            "X-Hub-Signature-256": _sign(raw_suspend, secret),
            "Content-Type": "application/json",
        },
    )
    assert rsp.status_code == 200
    assert rsp.json()["action"] == "suspend"

    with Session(engine) as s:
        row = s.get(GithubAppInstallation, installation_id)
        assert row is not None
        assert row.suspended_at is not None

    raw_unsuspend = json.dumps(
        {"action": "unsuspend", "installation": {"id": installation_id}}
    ).encode()
    rsu = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw_unsuspend,
        headers={
            "X-GitHub-Event": "installation",
            "X-Hub-Signature-256": _sign(raw_unsuspend, secret),
            "Content-Type": "application/json",
        },
    )
    assert rsu.status_code == 200

    with Session(engine) as s:
        row = s.get(GithubAppInstallation, installation_id)
        assert row is not None
        assert row.suspended_at is None
        s.delete(row)
        s.commit()


def test_github_webhooks_updates_existing_installation_row(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    installation_id = 909_090

    session = Session(engine)
    session.add(
        GithubAppInstallation(
            id=installation_id,
            account_id=1,
            account_login="old",
            account_type="Organization",
            target_type="Organization",
            repository_selection="selected",
            app_slug=None,
            suspended_at=get_datetime_utc(),
        ),
    )
    session.commit()
    session.close()

    payload = {
        "action": "created",
        "installation": {
            "id": installation_id,
            "target_type": "Organization",
            "repository_selection": None,
            "account": {"id": 202, "login": "renewed-org", "type": "Organization"},
        },
    }
    raw = json.dumps(payload).encode()
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

    with Session(engine) as s:
        row = s.get(GithubAppInstallation, installation_id)
        assert row is not None
        assert row.account_login == "renewed-org"
        assert row.account_id == 202
        assert row.repository_selection is None
        assert row.suspended_at is not None
        s.delete(row)
        s.commit()


def test_github_webhooks_duplicate_x_github_delivery_skips_processing(
    monkeypatch, client: TestClient
) -> None:
    """Same X-GitHub-Delivery twice: second response is idempotent (no mutation)."""
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    delivery = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    installation_id = 777_771
    payload = {
        "action": "created",
        "installation": {
            "id": installation_id,
            "repository_selection": "all",
            "app": {"slug": "dup-test"},
            "account": {"id": 1, "login": "first-name", "type": "User"},
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    hdrs = {
        "X-GitHub-Event": "installation",
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": _sign(raw, secret),
        "Content-Type": "application/json",
    }
    assert (
        client.post(
            f"{settings.API_V1_STR}/github/webhooks", content=raw, headers=hdrs
        ).status_code
        == 200
    )

    with Session(engine) as s:
        row = s.get(GithubAppInstallation, installation_id)
        assert row is not None
        assert row.account_login == "first-name"
        delivery_row = s.get(GithubWebhookDelivery, delivery)
        assert delivery_row is not None

    payload2 = {
        "action": "created",
        "installation": {
            "id": installation_id,
            "repository_selection": "all",
            "app": {"slug": "dup-test"},
            "account": {"id": 2, "login": "second-name", "type": "User"},
        },
    }
    raw2 = json.dumps(payload2).encode("utf-8")
    hdrs2 = {
        "X-GitHub-Event": "installation",
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": _sign(raw2, secret),
        "Content-Type": "application/json",
    }
    r2 = client.post(
        f"{settings.API_V1_STR}/github/webhooks", content=raw2, headers=hdrs2
    )
    assert r2.status_code == 200
    assert r2.json().get("idempotent") is True

    with Session(engine) as s:
        row = s.get(GithubAppInstallation, installation_id)
        assert row is not None
        assert row.account_login == "first-name"
        s.delete(row)
        s.commit()
        dr = s.get(GithubWebhookDelivery, delivery)
        if dr is not None:
            s.delete(dr)
            s.commit()


def test_github_webhooks_rate_limit_by_client_ip(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    monkeypatch.setattr(
        settings, "GITHUB_WEBHOOK_MAX_REQUESTS_PER_MINUTE_PER_IP", 2, raising=False
    )

    def _ping(delivery_suffix: str) -> object:
        raw = b"{}"
        return client.post(
            f"{settings.API_V1_STR}/github/webhooks",
            content=raw,
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": f"rate-{delivery_suffix}",
                "X-Hub-Signature-256": _sign(raw, secret),
                "Content-Type": "application/json",
            },
        )

    assert _ping("1").status_code == 200
    assert _ping("2").status_code == 200
    assert _ping("3").status_code == 429


def test_github_webhooks_rejects_invalid_date_header_when_skew_check_enabled(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_MAX_CLOCK_SKEW_SECONDS", 300)
    raw = b"{}"
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "Date": "not-a-date",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Date header"


def test_github_webhooks_rejects_old_date_header_when_skew_exceeded(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_MAX_CLOCK_SKEW_SECONDS", 300)
    raw = b"{}"
    old_date = format_datetime(datetime.now(timezone.utc) - timedelta(hours=2))
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "Date": old_date,
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Webhook Date outside allowed skew window"


def test_github_webhooks_accepts_valid_date_header_within_skew(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_MAX_CLOCK_SKEW_SECONDS", 300)
    raw = b"{}"
    near_now = format_datetime(datetime.now(timezone.utc) - timedelta(seconds=20))
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "Date": near_now,
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


def test_github_webhooks_suspend_missing_row_safe(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    payload = {"action": "suspend", "installation": {"id": 6_969_696}}
    raw = json.dumps(payload).encode()
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


def test_github_webhooks_installation_repositories_add_and_remove(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    installation_id = 123_321
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=installation_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="selected",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    payload_add = {
        "action": "added",
        "installation": {"id": installation_id},
        "repositories_added": [
            {"full_name": "acme/repo-a"},
            {"name": "repo-b", "owner": {"login": "acme"}},
        ],
        "repositories_removed": [],
    }
    raw_add = json.dumps(payload_add).encode("utf-8")
    resp_add = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw_add,
        headers={
            "X-GitHub-Event": "installation_repositories",
            "X-Hub-Signature-256": _sign(raw_add, secret),
            "Content-Type": "application/json",
        },
    )
    assert resp_add.status_code == 200
    assert resp_add.json()["repositories_added"] == 2

    with Session(engine) as session:
        repos = session.exec(
            select(GithubInstallationRepository).where(
                GithubInstallationRepository.installation_id == installation_id
            )
        ).all()
        names = {r.full_name for r in repos}
        assert names == {"acme/repo-a", "acme/repo-b"}

    payload_remove = {
        "action": "removed",
        "installation": {"id": installation_id},
        "repositories_added": [],
        "repositories_removed": [{"full_name": "acme/repo-a"}],
    }
    raw_remove = json.dumps(payload_remove).encode("utf-8")
    resp_remove = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw_remove,
        headers={
            "X-GitHub-Event": "installation_repositories",
            "X-Hub-Signature-256": _sign(raw_remove, secret),
            "Content-Type": "application/json",
        },
    )
    assert resp_remove.status_code == 200
    assert resp_remove.json()["repositories_removed"] == 1

    with Session(engine) as session:
        repos = session.exec(
            select(GithubInstallationRepository).where(
                GithubInstallationRepository.installation_id == installation_id
            )
        ).all()
        names = {r.full_name for r in repos}
        assert names == {"acme/repo-b"}


def test_github_webhooks_installation_repositories_unknown_installation_noop(
    monkeypatch, client: TestClient
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    payload = {
        "action": "added",
        "installation": {"id": 989_898_989},
        "repositories_added": [{"full_name": "acme/missing"}],
    }
    raw = json.dumps(payload).encode("utf-8")
    response = client.post(
        f"{settings.API_V1_STR}/github/webhooks",
        content=raw,
        headers={
            "X-GitHub-Event": "installation_repositories",
            "X-Hub-Signature-256": _sign(raw, secret),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


def test_github_webhooks_logs_installation_repositories_summary(
    monkeypatch, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret, raising=False)
    installation_id = 222_333
    with Session(engine) as session:
        session.add(
            GithubAppInstallation(
                id=installation_id,
                account_id=1,
                account_login="trainer",
                account_type="User",
                target_type="User",
                repository_selection="selected",
                app_slug="lesson-bot",
                suspended_at=None,
            ),
        )
        session.commit()

    payload = {
        "action": "added",
        "installation": {"id": installation_id},
        "repositories_added": [{"full_name": "acme/repo-z"}],
    }
    raw = json.dumps(payload).encode("utf-8")
    with caplog.at_level("INFO"):
        response = client.post(
            f"{settings.API_V1_STR}/github/webhooks",
            content=raw,
            headers={
                "X-GitHub-Event": "installation_repositories",
                "X-Hub-Signature-256": _sign(raw, secret),
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 200
    assert any(
        "installation_repositories processed" in rec.message for rec in caplog.records
    )
