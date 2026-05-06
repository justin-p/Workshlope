"""Branches in get_current_user (deps)."""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.crud import create_user
from app.models import UserCreate


def test_me_endpoint_rejects_bad_jwt_syntax(client: TestClient) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": "Bearer totally-not-jwt"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Could not validate credentials"


def test_me_endpoint_returns_404_when_user_removed(
    client: TestClient,
) -> None:
    phantom_id = uuid.uuid4()
    token = security.create_access_token(
        str(phantom_id),
        expires_delta=timedelta(minutes=2),
    )
    r = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "User not found"


def test_me_endpoint_rejects_inactive_user(client: TestClient, db: Session) -> None:
    email = f"inactive-me-{uuid.uuid4()}@example.com"
    user = create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_active=False,
            is_superuser=False,
        ),
    )
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=2),
    )
    r = client.get(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Inactive user"
