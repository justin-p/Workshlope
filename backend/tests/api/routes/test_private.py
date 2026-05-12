import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    LessonPrerequisite,
    SessionInstructor,
    User,
    WorkshopParticipant,
    WorkshopSession,
)


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


def test_create_user_can_set_instructor_flag(client: TestClient, db: Session) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "instructor@listo.com",
            "password": "password123",
            "full_name": "Instructor Listo",
            "is_instructor": True,
        },
    )

    assert r.status_code == 200
    data = r.json()
    user = db.exec(select(User).where(User.id == data["id"])).first()

    assert user is not None
    assert user.is_instructor is True


def test_private_bootstrap_e2e_workshop_initial_status_ended(
    client: TestClient, db: Session
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/?initial_status=ended",
    )
    assert r.status_code == 200
    sid = uuid.UUID(r.json()["session_id"])
    row = db.get(WorkshopSession, sid)
    assert row is not None
    assert row.status == "ended"
    assert row.current_part_index == 0


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


def test_private_bootstrap_e2e_workshop_omits_participant_seat_when_requested(
    client: TestClient, db: Session
) -> None:
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    assert su is not None

    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/"
        "?omit_participant_seat=true",
    )
    assert r.status_code == 200

    sid = uuid.UUID(r.json()["session_id"])

    seat = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == sid,
            WorkshopParticipant.user_id == su.id,
        )
    ).first()
    assert seat is None

    inst = db.exec(
        select(SessionInstructor).where(
            SessionInstructor.session_id == sid,
            SessionInstructor.user_id == su.id,
        )
    ).first()
    assert inst is not None


def test_private_bootstrap_distinct_trainee_lead_instructor_is_superuser(
    client: TestClient, db: Session
) -> None:
    """When participant_email != FIRST_SUPERUSER, lead instructor is the superuser."""
    email = f"e2e-trainee-{uuid.uuid4().hex}@example.com"
    assert (
        client.post(
            f"{settings.API_V1_STR}/private/users/",
            json={
                "email": email,
                "password": "password123",
                "full_name": "E2E Trainee",
            },
        ).status_code
        == 200
    )

    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/"
        f"?participant_email={email}",
    )
    assert r.status_code == 200
    sid = uuid.UUID(r.json()["session_id"])
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    trainee = db.exec(select(User).where(User.email == email)).first()
    assert su is not None and trainee is not None

    inst = db.exec(
        select(SessionInstructor).where(SessionInstructor.session_id == sid)
    ).all()
    assert len(inst) == 1
    assert inst[0].user_id == su.id

    seat = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == sid,
            WorkshopParticipant.user_id == trainee.id,
        )
    ).first()
    assert seat is not None


def test_private_bootstrap_e2e_workshop_with_incomplete_required_prerequisite(
    client: TestClient, db: Session
) -> None:
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    assert su is not None

    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/"
        "?with_incomplete_required_prerequisite=true",
    )
    assert r.status_code == 200

    sid = uuid.UUID(r.json()["session_id"])
    ws_row = db.get(WorkshopSession, sid)
    assert ws_row is not None

    prereq = db.exec(
        select(LessonPrerequisite).where(
            LessonPrerequisite.lesson_id == ws_row.lesson_id,
        )
    ).first()
    assert prereq is not None
    assert prereq.required_flag is True
    assert prereq.title == "E2E required pre-read"


def test_private_e2e_bootstrap_requires_existing_participant_user(
    client: TestClient,
) -> None:
    phantom = f"no-such-bootstrap-user-{uuid.uuid4().hex}@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/"
        f"?participant_email={phantom}",
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Participant user not found"


def test_private_e2e_distinct_trainee_requires_superuser_row_when_config_mismatched(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    phantom_su = "no-super-row@example.invalid"
    monkeypatch.setattr(settings, "FIRST_SUPERUSER", phantom_su, raising=False)
    email = f"trainee-only-{uuid.uuid4().hex}@example.com"
    assert (
        client.post(
            f"{settings.API_V1_STR}/private/users/",
            json={
                "email": email,
                "password": "password123",
                "full_name": "T",
            },
        ).status_code
        == 200
    )

    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/"
        f"?participant_email={email}",
    )
    assert r.status_code == 500


def test_private_bootstrap_e2e_workshop_can_start_scheduled(
    client: TestClient, db: Session
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/private/workshop/e2e-live-session/"
        "?initial_status=scheduled",
    )
    assert r.status_code == 200

    sid = uuid.UUID(r.json()["session_id"])
    row = db.get(WorkshopSession, sid)
    assert row is not None
    assert row.status == "scheduled"
