"""Workshop lesson prerequisites API behavior."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import Lesson, LessonPrerequisite, LessonRepo, UserCreate
from tests.utils.user import authentication_token_from_email


def _create_lesson(db: Session) -> Lesson:
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
    return lesson


def test_create_lesson_prerequisite_requires_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    actor_headers = authentication_token_from_email(
        client=client,
        email=f"ws06-actor-{uuid.uuid4()}@example.com",
        db=db,
    )

    response = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites",
        headers=actor_headers,
        json={"type": "task", "title": "Install tooling", "ordering": 0},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Instructor privileges required"


def test_create_lesson_prerequisite_instructor_success(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    email = f"ws06-inst-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(client=client, email=email, db=db)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites",
        headers=headers,
        json={
            "type": "task",
            "title": "Install tooling",
            "details": "Install Python and uv",
            "ordering": 1,
            "required_flag": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["lesson_id"] == str(lesson.id)
    assert payload["title"] == "Install tooling"
    assert payload["ordering"] == 1

    row = db.exec(
        select(LessonPrerequisite).where(
            LessonPrerequisite.lesson_id == lesson.id,
            LessonPrerequisite.title == "Install tooling",
        )
    ).first()
    assert row is not None
    assert row.required_flag is True


def test_read_lesson_prerequisites_ordered_for_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    email = f"ws06-inst-read-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(client=client, email=email, db=db)

    db.add(
        LessonPrerequisite(
            lesson_id=lesson.id,
            type="task",
            title="Second",
            ordering=2,
            required_flag=False,
        )
    )
    db.add(
        LessonPrerequisite(
            lesson_id=lesson.id,
            type="task",
            title="First",
            ordering=1,
            required_flag=True,
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert [item["title"] for item in payload["data"]] == ["First", "Second"]
