import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Lesson,
    LessonRepo,
    SessionInstructor,
    User,
    WorkshopSession,
)
from tests.utils.user import authentication_token_from_email


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
        slug=f"lesson-{uuid.uuid4()}",
        title="Lesson",
        lesson_sync_generation=1,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    session_row = WorkshopSession(
        lesson_id=lesson.id,
        status="live",
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    return session_row


def _instructor_headers(client: TestClient, db: Session) -> tuple[dict[str, str], User]:
    email = f"badge-instructor-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=email, db=db)
    instructor = db.exec(select(User).where(User.email == email)).first()
    assert instructor is not None
    instructor.is_instructor = True
    db.add(instructor)
    db.commit()
    db.refresh(instructor)
    return headers, instructor


def test_badge_catalog_requires_instructor(client: TestClient, db: Session) -> None:
    normal_headers = authentication_token_from_email(
        client=client, email=f"badge-user-{uuid.uuid4()}@example.com", db=db
    )
    denied = client.get(
        f"{settings.API_V1_STR}/workshop/badges", headers=normal_headers
    )
    assert denied.status_code == 403

    headers, _ = _instructor_headers(client, db)
    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-{uuid.uuid4()}",
            "title": "Fast finisher",
            "points": 5,
        },
    )
    assert create.status_code == 200
    assert create.json()["points"] == 5

    listed = client.get(f"{settings.API_V1_STR}/workshop/badges", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1


def test_grant_revoke_and_leaderboard(client: TestClient, db: Session) -> None:
    headers, instructor = _instructor_headers(client, db)
    session_row = _create_live_session(db)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        )
    )
    db.commit()

    trainee_email = f"badge-trainee-{uuid.uuid4()}@example.com"
    trainee_headers = authentication_token_from_email(
        client=client, email=trainee_email, db=db
    )
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None

    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-{uuid.uuid4()}",
            "title": "Great helper",
            "points": 3,
        },
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]

    grant = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
        headers=headers,
        json={"user_id": str(trainee.id), "badge_id": badge_id},
    )
    assert grant.status_code == 200

    leaderboard = client.get(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/leaderboard",
        headers=headers,
    )
    assert leaderboard.status_code == 200
    assert leaderboard.json()["count"] == 1
    assert leaderboard.json()["data"][0]["total_points"] == 3

    revoke = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={
            "user_id": str(trainee.id),
            "badge_id": badge_id,
            "reason": "mistaken award",
        },
    )
    assert revoke.status_code == 200

    leaderboard_after = client.get(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/leaderboard",
        headers=headers,
    )
    assert leaderboard_after.status_code == 200
    assert leaderboard_after.json()["count"] == 0

    denied = client.get(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/leaderboard",
        headers=trainee_headers,
    )
    assert denied.status_code == 403
