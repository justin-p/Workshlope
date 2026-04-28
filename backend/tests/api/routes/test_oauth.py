"""Tests for the GitHub OAuth bridge and pending-approval admin endpoints.

Covers the pending-approval policy, is_active enforcement, role preservation,
admin pending list/approve/deny, and admin unlink/status flows. The Auth.js
boundary is mocked by signing bridge tokens with the shared secret directly in
the tests.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import crud
from app.core import security
from app.core.config import settings
from app.models import OAuthAccount, PendingGitHubLogin, User, UserCreate
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_active_user(db: Session, *, is_active: bool = True) -> User:
    return crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=random_lower_string(),
            is_active=is_active,
            is_superuser=False,
        ),
    )


def _bridge_token(provider_account_id: str, **extra: object) -> str:
    return security.create_bridge_token(
        provider_account_id=provider_account_id,
        **extra,
    )


# ---------------------------------------------------------------------------
# Bridge endpoint
# ---------------------------------------------------------------------------


class TestBridgeTokenValidation:
    """Bridge token must be a valid signed token for the configured audience."""

    def test_invalid_signature_returns_401(self, client: TestClient) -> None:
        forged = jwt.encode(
            {
                "iss": settings.GITHUB_BRIDGE_ISSUER,
                "aud": settings.GITHUB_BRIDGE_AUDIENCE,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=1),
                "provider": "github",
                "provider_account_id": "1",
            },
            "wrong-secret",
            algorithm="HS256",
        )
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": forged})
        assert r.status_code == 401

    def test_expired_token_returns_401(self, client: TestClient) -> None:
        token = security.create_bridge_token(
            provider_account_id="1",
            expires_delta=timedelta(seconds=-1),
        )
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r.status_code == 401

    def test_non_github_provider_rejected(self, client: TestClient) -> None:
        token = security.create_bridge_token(
            provider="gitlab",
            provider_account_id="1",
        )
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r.status_code == 400


class TestBridgeLinkedFlow:
    """Linked accounts sign in directly; is_active is enforced."""

    def test_linked_active_user_returns_signed_in(
        self, client: TestClient, db: Session
    ) -> None:
        user = _create_active_user(db)
        crud.create_oauth_account(
            session=db,
            user_id=user.id,
            provider="github",
            provider_account_id="123",
            provider_login="alice",
        )
        token = _bridge_token(provider_account_id="123")
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "signed_in"
        assert body["pending_id"] is None
        cookie_token = r.cookies.get("access_token")
        assert cookie_token
        decoded = jwt.decode(cookie_token, settings.SECRET_KEY, algorithms=["HS256"])
        assert decoded["sub"] == str(user.id)

    def test_linked_inactive_user_denied(self, client: TestClient, db: Session) -> None:
        user = _create_active_user(db, is_active=False)
        crud.create_oauth_account(
            session=db,
            user_id=user.id,
            provider="github",
            provider_account_id="124",
        )
        token = _bridge_token(provider_account_id="124")
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r.status_code == 403


class TestBridgePendingFlow:
    """First-time GitHub identities create a pending-approval record."""

    def test_unlinked_creates_pending(self, client: TestClient, db: Session) -> None:
        token = _bridge_token(
            provider_account_id="42",
            provider_login="newcomer",
            email="newcomer@example.com",
        )
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "pending_approval"
        assert body["pending_id"]

        pending = crud.get_pending_github_login(
            session=db, provider="github", provider_account_id="42"
        )
        assert pending is not None
        assert pending.provider_login == "newcomer"
        assert pending.email == "newcomer@example.com"
        assert pending.attempt_count == 1

    def test_repeat_unlinked_increments_attempt_count(
        self, client: TestClient, db: Session
    ) -> None:
        token = _bridge_token(
            provider_account_id="43",
            provider_login="repeater",
            email="repeater@example.com",
        )
        r1 = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        r2 = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["pending_id"] == r2.json()["pending_id"]

        pending = crud.get_pending_github_login(
            session=db, provider="github", provider_account_id="43"
        )
        assert pending is not None
        assert pending.attempt_count == 2


class TestBridgeRolePreservation:
    """GitHub login must not change a user's role flags."""

    def test_superuser_role_is_preserved(self, client: TestClient, db: Session) -> None:
        user = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(),
                password=random_lower_string(),
                is_superuser=True,
            ),
        )
        crud.create_oauth_account(
            session=db,
            user_id=user.id,
            provider="github",
            provider_account_id="1000",
        )
        token = _bridge_token(provider_account_id="1000")
        r = client.post(f"{API}/oauth/github/bridge", json={"bridge_token": token})
        assert r.status_code == 200
        access_token = r.cookies.get("access_token")
        assert access_token

        me = client.get(
            f"{API}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me.status_code == 200
        assert me.json()["is_superuser"] is True


# ---------------------------------------------------------------------------
# Admin pending list / approve / deny
# ---------------------------------------------------------------------------


class TestAdminPendingList:
    def test_list_requires_superuser(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
    ) -> None:
        r = client.get(f"{API}/oauth/github/pending", headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_returns_pending_rows(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="200",
            provider_login="octo",
            email="octo@example.com",
        )
        r = client.get(f"{API}/oauth/github/pending", headers=superuser_token_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] >= 1
        ids = [row["provider_account_id"] for row in body["data"]]
        assert "200" in ids


class TestAdminApproveLinkExisting:
    def test_approve_link_existing_success(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        user = _create_active_user(db)
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="300",
            provider_login="bob",
            email=user.email,
        )
        pending_id = pending.id
        r = client.post(
            f"{API}/oauth/github/pending/{pending_id}/approve",
            json={"user_id": str(user.id)},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == str(user.id)
        assert body["provider_account_id"] == "300"
        assert body["provider_login"] == "bob"
        db.expire_all()
        assert (
            crud.get_pending_github_login_by_id(session=db, pending_id=pending_id)
            is None
        )

    def test_approve_link_existing_unknown_user_404(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="301",
        )
        import uuid as uuid_lib

        r = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"user_id": str(uuid_lib.uuid4())},
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_approve_link_existing_user_already_linked_409(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        user = _create_active_user(db)
        crud.create_oauth_account(
            session=db,
            user_id=user.id,
            provider="github",
            provider_account_id="999",
        )
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="302",
        )
        r = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"user_id": str(user.id)},
            headers=superuser_token_headers,
        )
        assert r.status_code == 409

    def test_approve_link_existing_github_already_linked_409(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        first_user = _create_active_user(db)
        crud.create_oauth_account(
            session=db,
            user_id=first_user.id,
            provider="github",
            provider_account_id="303",
        )
        # Despite the unique constraint, simulate a stray pending row to make
        # sure the route blocks before attempting to insert a duplicate
        # OAuthAccount. We can't have both an OAuthAccount and a pending row
        # for the same provider_account_id under normal flow, but the route
        # must still defend against it.
        other_user = _create_active_user(db)
        pending = PendingGitHubLogin(
            provider="github",
            provider_account_id="303",
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)

        r = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"user_id": str(other_user.id)},
            headers=superuser_token_headers,
        )
        assert r.status_code == 409


class TestAdminApproveCreateNew:
    def test_approve_create_new_success(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        email = random_email()
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="400",
            provider_login="newuser",
            email=email,
            full_name="New User",
        )
        r = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"create_user": True},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        body = r.json()

        new_user = crud.get_user_by_email(session=db, email=email)
        assert new_user is not None
        assert new_user.is_active is True
        assert new_user.is_superuser is False
        assert new_user.full_name == "New User"
        assert body["user_id"] == str(new_user.id)

    def test_approve_create_new_email_collision_409(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        existing = _create_active_user(db)
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="401",
            email=existing.email,
        )
        r = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"create_user": True},
            headers=superuser_token_headers,
        )
        assert r.status_code == 409

    def test_approve_create_new_without_email_400(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="402",
        )
        r = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"create_user": True},
            headers=superuser_token_headers,
        )
        assert r.status_code == 400


class TestAdminApproveValidation:
    def test_must_provide_one_of_user_id_or_create_user(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="500",
        )
        # Neither
        r1 = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={},
            headers=superuser_token_headers,
        )
        assert r1.status_code == 422

        # Both
        user = _create_active_user(db)
        r2 = client.post(
            f"{API}/oauth/github/pending/{pending.id}/approve",
            json={"user_id": str(user.id), "create_user": True},
            headers=superuser_token_headers,
        )
        assert r2.status_code == 422

    def test_unknown_pending_id_returns_404(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
    ) -> None:
        import uuid as uuid_lib

        r = client.post(
            f"{API}/oauth/github/pending/{uuid_lib.uuid4()}/approve",
            json={"create_user": True},
            headers=superuser_token_headers,
        )
        assert r.status_code == 404


class TestAdminDenyPending:
    def test_deny_removes_pending_row(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        pending = crud.upsert_pending_github_login(
            session=db,
            provider="github",
            provider_account_id="600",
        )
        pending_id = pending.id
        r = client.delete(
            f"{API}/oauth/github/pending/{pending_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        db.expire_all()
        assert (
            crud.get_pending_github_login_by_id(session=db, pending_id=pending_id)
            is None
        )

    def test_deny_unknown_pending_returns_404(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
    ) -> None:
        import uuid as uuid_lib

        r = client.delete(
            f"{API}/oauth/github/pending/{uuid_lib.uuid4()}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Admin unlink / status endpoints (kept)
# ---------------------------------------------------------------------------


class TestAdminUnlinkAndStatus:
    def test_unlink_removes_link(
        self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]
    ) -> None:
        user = _create_active_user(db)
        crud.create_oauth_account(
            session=db,
            user_id=user.id,
            provider="github",
            provider_account_id="7000",
        )
        r = client.delete(
            f"{API}/oauth/github/users/{user.id}/link",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert (
            crud.get_oauth_account_for_user(
                session=db, user_id=user.id, provider="github"
            )
            is None
        )

    def test_unlink_when_no_link_returns_404(
        self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]
    ) -> None:
        user = _create_active_user(db)
        r = client.delete(
            f"{API}/oauth/github/users/{user.id}/link",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_status_returns_linked_account(
        self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]
    ) -> None:
        user = _create_active_user(db)
        crud.create_oauth_account(
            session=db,
            user_id=user.id,
            provider="github",
            provider_account_id="8000",
            provider_login="dave",
        )
        r = client.get(
            f"{API}/oauth/github/users/{user.id}/status",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["provider_login"] == "dave"

    def test_status_returns_null_when_unlinked(
        self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]
    ) -> None:
        user = _create_active_user(db)
        r = client.get(
            f"{API}/oauth/github/users/{user.id}/status",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json() is None


# ---------------------------------------------------------------------------
# Removed endpoints smoke test
# ---------------------------------------------------------------------------


class TestRemovedEndpoints:
    """Old invite / manual-link endpoints must no longer be present."""

    def test_invite_endpoint_gone(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        user = _create_active_user(db)
        r = client.post(
            f"{API}/oauth/github/users/{user.id}/invite",
            headers=superuser_token_headers,
        )
        assert r.status_code in (404, 405)

    def test_manual_link_endpoint_gone(
        self,
        client: TestClient,
        db: Session,
        superuser_token_headers: dict[str, str],
    ) -> None:
        user = _create_active_user(db)
        r = client.post(
            f"{API}/oauth/github/users/{user.id}/link",
            json={"provider_account_id": "1"},
            headers=superuser_token_headers,
        )
        assert r.status_code in (404, 405)


@pytest.fixture(autouse=True)
def _clean_oauth_state(db: Session):
    """Wipe OAuth/Pending rows between tests in this module so per-user
    assertions about counts/state are deterministic."""
    yield
    db.execute(delete(PendingGitHubLogin))
    db.execute(delete(OAuthAccount))
    db.commit()
