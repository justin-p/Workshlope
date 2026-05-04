"""Workshop lesson prerequisites API behavior."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Lesson,
    LessonPrerequisite,
    LessonRepo,
    User,
    UserCreate,
    UserPrerequisiteCompletion,
)
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


def test_complete_prerequisite_creates_user_completion(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    learner_email = f"ws06-learner-{uuid.uuid4()}@example.com"
    learner_headers = authentication_token_from_email(
        client=client,
        email=learner_email,
        db=db,
    )
    learner = db.exec(select(User).where(User.email == learner_email)).first()
    assert learner is not None
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Install uv",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}/complete",
        headers=learner_headers,
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Prerequisite marked complete"

    completion = db.exec(
        select(UserPrerequisiteCompletion).where(
            UserPrerequisiteCompletion.prerequisite_id == prerequisite.id
        )
    ).first()
    assert completion is not None
    assert completion.user_id == learner.id
    assert completion.lesson_id == lesson.id
    assert completion.source == "self"


def test_complete_prerequisite_idempotent_for_same_user(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    learner_email = f"ws06-learner-idem-{uuid.uuid4()}@example.com"
    learner_headers = authentication_token_from_email(
        client=client,
        email=learner_email,
        db=db,
    )
    learner = db.exec(select(User).where(User.email == learner_email)).first()
    assert learner is not None
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Clone repo",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    url = f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}/complete"
    r1 = client.post(url, headers=learner_headers)
    r2 = client.post(url, headers=learner_headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    rows = db.exec(
        select(UserPrerequisiteCompletion).where(
            UserPrerequisiteCompletion.user_id == learner.id,
            UserPrerequisiteCompletion.prerequisite_id == prerequisite.id,
        )
    ).all()
    assert len(rows) == 1


def test_complete_prerequisite_other_user_requires_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    actor_headers = authentication_token_from_email(
        client=client,
        email=f"ws06-non-inst-{uuid.uuid4()}@example.com",
        db=db,
    )
    target_email = f"ws06-target-{uuid.uuid4()}@example.com"
    target_headers = authentication_token_from_email(
        client=client, email=target_email, db=db
    )
    del target_headers
    target = db.exec(select(User).where(User.email == target_email)).first()
    assert target is not None
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Read docs",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}/complete",
        headers=actor_headers,
        json={"user_id": str(target.id)},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Instructor privileges required"


def test_complete_prerequisite_instructor_can_mark_other_user(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-inst-complete-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    learner_email = f"ws06-learner-target-{uuid.uuid4()}@example.com"
    learner_headers = authentication_token_from_email(
        client=client, email=learner_email, db=db
    )
    del learner_headers
    learner = db.exec(select(User).where(User.email == learner_email)).first()
    assert learner is not None

    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Set up environment",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    response = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}/complete",
        headers=instructor_headers,
        json={"user_id": str(learner.id)},
    )
    assert response.status_code == 200

    completion = db.exec(
        select(UserPrerequisiteCompletion).where(
            UserPrerequisiteCompletion.user_id == learner.id,
            UserPrerequisiteCompletion.prerequisite_id == prerequisite.id,
        )
    ).first()
    assert completion is not None
    assert completion.source == "instructor"


def test_read_my_lesson_prerequisites_includes_completion_status(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    learner_email = f"ws06-prereq-me-{uuid.uuid4()}@example.com"
    learner_headers = authentication_token_from_email(
        client=client, email=learner_email, db=db
    )
    learner = db.exec(select(User).where(User.email == learner_email)).first()
    assert learner is not None

    first = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Install uv",
        ordering=1,
        required_flag=True,
    )
    second = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Clone repo",
        ordering=2,
        required_flag=False,
    )
    db.add(first)
    db.add(second)
    db.commit()
    db.refresh(first)
    db.refresh(second)
    db.add(
        UserPrerequisiteCompletion(
            user_id=learner.id,
            lesson_id=lesson.id,
            prerequisite_id=second.id,
            source="self",
        )
    )
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/me",
        headers=learner_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert [item["title"] for item in payload["data"]] == ["Install uv", "Clone repo"]
    assert payload["data"][0]["is_completed"] is False
    assert payload["data"][1]["is_completed"] is True
    assert payload["data"][1]["source"] == "self"


def test_read_my_lesson_prerequisites_returns_404_for_missing_lesson(
    client: TestClient, db: Session
) -> None:
    headers = authentication_token_from_email(
        client=client,
        email=f"ws06-prereq-me-missing-{uuid.uuid4()}@example.com",
        db=db,
    )
    missing = uuid.uuid4()
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{missing}/prerequisites/me",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Lesson not found"


def test_patch_lesson_prerequisite_requires_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    actor_headers = authentication_token_from_email(
        client=client,
        email=f"ws06-prereq-patch-actor-{uuid.uuid4()}@example.com",
        db=db,
    )
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Read intro",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    response = client.patch(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}",
        headers=actor_headers,
        json={"title": "Read updated intro"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Instructor privileges required"


def test_patch_lesson_prerequisite_updates_fields(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-prereq-patch-inst-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Old title",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    response = client.patch(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}",
        headers=headers,
        json={"title": "New title", "required_flag": False, "ordering": 3},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "New title"
    assert payload["required_flag"] is False
    assert payload["ordering"] == 3

    db.refresh(prerequisite)
    assert prerequisite.title == "New title"
    assert prerequisite.required_flag is False
    assert prerequisite.ordering == 3


def test_patch_lesson_prerequisite_returns_404_for_missing_prerequisite(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-prereq-patch-missing-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    missing = uuid.uuid4()

    response = client.patch(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{missing}",
        headers=headers,
        json={"title": "No row"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Prerequisite not found"


def test_delete_lesson_prerequisite_requires_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    actor_headers = authentication_token_from_email(
        client=client,
        email=f"ws06-prereq-delete-actor-{uuid.uuid4()}@example.com",
        db=db,
    )
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Cleanup workspace",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    response = client.delete(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite.id}",
        headers=actor_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Instructor privileges required"


def test_delete_lesson_prerequisite_instructor_success(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-prereq-delete-inst-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Install tooling",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)
    prerequisite_id = prerequisite.id

    response = client.delete(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{prerequisite_id}",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Prerequisite deleted"

    db.expire_all()
    deleted = db.get(LessonPrerequisite, prerequisite_id)
    assert deleted is None


def test_delete_lesson_prerequisite_returns_404_for_missing_prerequisite(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-prereq-delete-missing-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=instructor_email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )

    response = client.delete(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{uuid.uuid4()}",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Prerequisite not found"
