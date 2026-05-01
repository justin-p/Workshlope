import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User, WorkshopParticipant, WorkshopSession


def test_create_user(client: TestClient, db: Session) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "pollo@listo.com",
            "password": "password123",
            "full_name": "Pollo Listo",
        },
    )

    assert r.status_code == 200

    data = r.json()

    user = db.exec(select(User).where(User.id == data["id"])).first()

    assert user
    assert user.email == "pollo@listo.com"
    assert user.full_name == "Pollo Listo"


def test_private_bootstrap_e2e_workshop_live_session(
    client: TestClient, db: Session
) -> None:
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    assert su is not None

    r = client.post(f"{settings.API_V1_STR}/private/workshop/e2e-live-session/")
    assert r.status_code == 200

    sid = uuid.UUID(r.json()["session_id"])
    row = db.get(WorkshopSession, sid)
    assert row is not None
    assert row.status == "live"

    seat = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == sid,
            WorkshopParticipant.user_id == su.id,
        )
    ).first()
    assert seat is not None
    assert seat.joined_at is not None
