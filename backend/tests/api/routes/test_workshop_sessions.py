import uuid
from datetime import datetime, timezone

import jwt
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import Lesson, LessonRepo, User, WorkshopParticipant, WorkshopSession


def _create_live_session(db: Session) -> WorkshopSession:
    repo = LessonRepo(
        full_name=f"org/repo-{uuid.uuid4()}",
        default_branch="main",
        health="healthy",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    lesson = Lesson(
        repo_id=repo.id,
        slug=f"intro-{uuid.uuid4()}",
        title="Intro",
        lesson_sync_generation=1,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    session = WorkshopSession(
        lesson_id=lesson.id,
        status="live",
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def test_enter_rejected_when_session_scheduled(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session = _create_live_session(db)
    session.status = "scheduled"
    db.add(session)
    db.commit()
    db.refresh(session)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/enter",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403


def test_ws_ticket_requires_roster_membership(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session = _create_live_session(db)
    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "User is not part of this session"


def test_ws_ticket_returns_signed_claims_for_joined_participant(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    decoded = jwt.decode(
        payload["ticket"],
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        audience="workshop-ws",
    )
    assert decoded["sid"] == str(session.id)
    assert decoded["uid"] == str(user.id)
    assert decoded["role"] == "participant"
