import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Lesson, LessonRepo, WorkshopSession


def test_enter_rejected_when_session_scheduled(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
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
        slug="intro",
        title="Intro",
        lesson_sync_generation=1,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    session = WorkshopSession(
        lesson_id=lesson.id,
        status="scheduled",
        created_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session.id}/enter",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
