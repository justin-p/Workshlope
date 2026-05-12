"""Workshop lesson prerequisites API behavior."""

import uuid
from datetime import datetime, timezone

import pytest
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
    WorkshopParticipant,
    WorkshopSession,
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


def _create_scheduled_workshop_session(db: Session, lesson: Lesson) -> WorkshopSession:
    ws = WorkshopSession(
        lesson_id=lesson.id,
        status="scheduled",
        created_at=datetime.now(timezone.utc),
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


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


def test_read_lesson_prerequisite_gaps_requires_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    headers = authentication_token_from_email(
        client=client,
        email=f"ws06-gaps-actor-{uuid.uuid4()}@example.com",
        db=db,
    )
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 403


def test_read_lesson_prerequisite_gaps_requires_session_id_query(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-gaps-q-{uuid.uuid4()}@example.com"
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
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=headers,
    )
    assert response.status_code == 422


def test_read_lesson_prerequisite_gaps_lesson_not_found(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    instructor_email = f"ws06-gaps-lesson-{uuid.uuid4()}@example.com"
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
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{uuid.uuid4()}/prerequisites/gaps",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Lesson not found"


def test_read_lesson_prerequisite_gaps_session_not_found(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-gaps-session-{uuid.uuid4()}@example.com"
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
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=headers,
        params={"session_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_read_lesson_prerequisite_gaps_session_lesson_mismatch_returns_422(
    client: TestClient, db: Session
) -> None:
    lesson_a = _create_lesson(db)
    lesson_b = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson_a)
    instructor_email = f"ws06-gaps-mismatch-{uuid.uuid4()}@example.com"
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
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson_b.id}/prerequisites/gaps",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Session does not belong to this lesson"


def test_read_lesson_prerequisite_gaps_lists_incomplete_required_with_identity(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)

    learner_email = f"ws06-gaps-learner-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=learner_email, db=db)
    learner = db.exec(select(User).where(User.email == learner_email)).first()
    assert learner is not None

    first = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Done task",
        ordering=1,
        required_flag=True,
    )
    second = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Still owed",
        ordering=2,
        required_flag=True,
    )
    db.add(first)
    db.add(second)
    db.commit()
    db.refresh(first)
    db.refresh(second)

    db.add(
        WorkshopParticipant(
            session_id=ws.id,
            user_id=learner.id,
            invited_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        UserPrerequisiteCompletion(
            user_id=learner.id,
            lesson_id=lesson.id,
            prerequisite_id=first.id,
            source="self",
        )
    )
    db.commit()

    instructor_email = f"ws06-gaps-inst-{uuid.uuid4()}@example.com"
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

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=instructor_headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    row = payload["data"][0]
    assert row["user_id"] == str(learner.id)
    assert row["email"] == learner_email
    titles = [p["title"] for p in row["incomplete_required_prerequisites"]]
    assert titles == ["Still owed"]


def test_read_lesson_prerequisite_gaps_omits_removed_participant(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Required gate",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    active_email = f"ws06-gaps-active-{uuid.uuid4()}@example.com"
    removed_email = f"ws06-gaps-removed-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=active_email, db=db)
    authentication_token_from_email(client=client, email=removed_email, db=db)
    active_user = db.exec(select(User).where(User.email == active_email)).first()
    removed_user = db.exec(select(User).where(User.email == removed_email)).first()
    assert active_user is not None
    assert removed_user is not None

    db.add(
        WorkshopParticipant(
            session_id=ws.id,
            user_id=active_user.id,
            invited_at=datetime.now(timezone.utc),
        )
    )
    removed_participant = WorkshopParticipant(
        session_id=ws.id,
        user_id=removed_user.id,
        invited_at=datetime.now(timezone.utc),
        removed_at=datetime.now(timezone.utc),
    )
    db.add(removed_participant)
    db.commit()

    instructor_email = f"ws06-gaps-omit-{uuid.uuid4()}@example.com"
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

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=instructor_headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["data"][0]["email"] == active_email


def test_read_lesson_prerequisite_gaps_empty_when_all_required_complete(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    learner_email = f"ws06-gaps-clear-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=learner_email, db=db)
    learner = db.exec(select(User).where(User.email == learner_email)).first()
    assert learner is not None

    req = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Must do",
        ordering=1,
        required_flag=True,
    )
    opt = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Nice to have",
        ordering=2,
        required_flag=False,
    )
    db.add(req)
    db.add(opt)
    db.commit()
    db.refresh(req)
    db.refresh(opt)

    db.add(
        WorkshopParticipant(
            session_id=ws.id,
            user_id=learner.id,
            invited_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        UserPrerequisiteCompletion(
            user_id=learner.id,
            lesson_id=lesson.id,
            prerequisite_id=req.id,
            source="self",
        )
    )
    db.commit()

    instructor_email = f"ws06-gaps-empty-{uuid.uuid4()}@example.com"
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

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=instructor_headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 200
    assert response.json() == {"data": [], "count": 0}


def test_read_lesson_prerequisite_aggregates_requires_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    headers = authentication_token_from_email(
        client=client,
        email=f"ws06-aggr-actor-{uuid.uuid4()}@example.com",
        db=db,
    )
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/aggregates",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 403


def test_read_lesson_prerequisite_aggregates_requires_session_id_query(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    instructor_email = f"ws06-aggr-q-{uuid.uuid4()}@example.com"
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
    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/aggregates",
        headers=headers,
    )
    assert response.status_code == 422


def test_read_lesson_prerequisite_aggregates_counts_roster_and_completions(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)

    email_a = f"ws06-aggr-a-{uuid.uuid4()}@example.com"
    email_b = f"ws06-aggr-b-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=email_a, db=db)
    authentication_token_from_email(client=client, email=email_b, db=db)
    user_a = db.exec(select(User).where(User.email == email_a)).first()
    user_b = db.exec(select(User).where(User.email == email_b)).first()
    assert user_a is not None
    assert user_b is not None

    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Shared checklist",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    for u in (user_a, user_b):
        db.add(
            WorkshopParticipant(
                session_id=ws.id,
                user_id=u.id,
                invited_at=datetime.now(timezone.utc),
            )
        )
    db.add(
        UserPrerequisiteCompletion(
            user_id=user_a.id,
            lesson_id=lesson.id,
            prerequisite_id=prerequisite.id,
            source="self",
        )
    )
    db.commit()

    instructor_email = f"ws06-aggr-inst-{uuid.uuid4()}@example.com"
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

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/aggregates",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    row = payload["data"][0]
    assert row["roster_count"] == 2
    assert row["completed_count"] == 1
    assert row["prerequisite"]["title"] == "Shared checklist"


def test_read_lesson_prerequisite_aggregates_zero_roster_still_lists_prerequisites(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    db.add(
        LessonPrerequisite(
            lesson_id=lesson.id,
            type="task",
            title="Solo prereq",
            ordering=1,
            required_flag=True,
        )
    )
    db.commit()

    instructor_email = f"ws06-aggr-zero-{uuid.uuid4()}@example.com"
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

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/aggregates",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["data"][0]["roster_count"] == 0
    assert payload["data"][0]["completed_count"] == 0


def test_read_lesson_prerequisite_aggregates_excludes_removed_participant_from_roster(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    prerequisite = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Gate",
        ordering=1,
        required_flag=True,
    )
    db.add(prerequisite)
    db.commit()
    db.refresh(prerequisite)

    active_email = f"ws06-aggr-act-{uuid.uuid4()}@example.com"
    removed_email = f"ws06-aggr-rem-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=active_email, db=db)
    authentication_token_from_email(client=client, email=removed_email, db=db)
    active_user = db.exec(select(User).where(User.email == active_email)).first()
    removed_user = db.exec(select(User).where(User.email == removed_email)).first()
    assert active_user is not None and removed_user is not None

    db.add(
        WorkshopParticipant(
            session_id=ws.id,
            user_id=active_user.id,
            invited_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=ws.id,
            user_id=removed_user.id,
            invited_at=datetime.now(timezone.utc),
            removed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    instructor_email = f"ws06-aggr-omit-{uuid.uuid4()}@example.com"
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

    response = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/aggregates",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["roster_count"] == 1


def test_create_prerequisite_404_when_lesson_missing(
    client: TestClient, db: Session
) -> None:
    email = f"ws-lesson-miss-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(client=client, email=email, db=db)
    missing = uuid.uuid4()
    r = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{missing}/prerequisites",
        headers=headers,
        json={"type": "task", "title": "T", "ordering": 0},
    )
    assert r.status_code == 404


def test_complete_prerequisite_404_unknown_target_user(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    email = f"ws-complete-miss-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(client=client, email=email, db=db)
    pre = LessonPrerequisite(
        lesson_id=lesson.id,
        type="reading",
        title="Doc",
        details="",
        ordering=0,
        required_flag=False,
    )
    db.add(pre)
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/"
        f"{pre.id}/complete",
        headers=headers,
        json={"user_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


def _instructor_headers(client: TestClient, db: Session) -> dict[str, str]:
    email = f"ws06-pr404-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    return authentication_token_from_email(client=client, email=email, db=db)


def test_patch_prerequisite_404_lesson_not_found(
    client: TestClient, db: Session
) -> None:
    headers = _instructor_headers(client, db)
    missing_lesson = uuid.uuid4()
    r = client.patch(
        f"{settings.API_V1_STR}/workshop/lessons/{missing_lesson}/prerequisites/"
        f"{uuid.uuid4()}",
        headers=headers,
        json={"title": "Nope"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Lesson not found"


def test_patch_prerequisite_404_row_not_found(client: TestClient, db: Session) -> None:
    lesson = _create_lesson(db)
    headers = _instructor_headers(client, db)
    r = client.patch(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/"
        f"{uuid.uuid4()}",
        headers=headers,
        json={"title": "Nope"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Prerequisite not found"


def test_delete_and_list_prerequisite_404_lesson_not_found(
    client: TestClient, db: Session
) -> None:
    headers = _instructor_headers(client, db)
    lid = uuid.uuid4()
    pre_id = uuid.uuid4()

    deleted = client.delete(
        f"{settings.API_V1_STR}/workshop/lessons/{lid}/prerequisites/{pre_id}",
        headers=headers,
    )
    assert deleted.status_code == 404
    assert deleted.json()["detail"] == "Lesson not found"

    listed = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lid}/prerequisites",
        headers=headers,
    )
    assert listed.status_code == 404
    assert listed.json()["detail"] == "Lesson not found"


def test_complete_prerequisite_404_lesson_not_found(
    client: TestClient, db: Session
) -> None:
    learner_headers = authentication_token_from_email(
        client=client,
        email=f"ws06-complete-lesson-{uuid.uuid4()}@example.com",
        db=db,
    )
    r = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{uuid.uuid4()}/prerequisites/"
        f"{uuid.uuid4()}/complete",
        headers=learner_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Lesson not found"


def test_complete_prerequisite_404_prerequisite_not_found(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    learner_headers = authentication_token_from_email(
        client=client,
        email=f"ws06-complete-pre-{uuid.uuid4()}@example.com",
        db=db,
    )
    r = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/"
        f"{uuid.uuid4()}/complete",
        headers=learner_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Prerequisite not found"


def test_patch_prerequisite_updates_type_details_and_url(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    headers = _instructor_headers(client, db)
    create = client.post(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites",
        headers=headers,
        json={"type": "task", "title": "Orig", "ordering": 0},
    )
    assert create.status_code == 200
    pre_id = create.json()["id"]

    patched = client.patch(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/{pre_id}",
        headers=headers,
        json={
            "type": "reading",
            "details": "See chapter 2",
            "url": "https://example.com/doc",
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["type"] == "reading"
    assert body["details"] == "See chapter 2"
    assert body["url"] == "https://example.com/doc"


def test_prerequisite_gaps_skip_roster_ids_with_no_user_row(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lesson = _create_lesson(db)
    ws = _create_scheduled_workshop_session(db, lesson)
    pre = LessonPrerequisite(
        lesson_id=lesson.id,
        type="task",
        title="Req",
        ordering=0,
        required_flag=True,
    )
    db.add(pre)
    db.commit()

    instructor_email = f"ws06-gap-null-{uuid.uuid4()}@example.com"
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

    orphan = uuid.uuid4()
    monkeypatch.setattr(
        "app.api.routes.workshop_lessons._active_trainee_roster_user_ids_for_session",
        lambda *, session, session_id: [orphan],
    )

    r = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/prerequisites/gaps",
        headers=headers,
        params={"session_id": str(ws.id)},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_read_lesson_roster_user_picker_requires_instructor(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    lesson = _create_lesson(db)
    r = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/roster-user-picker",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403


def test_read_lesson_roster_user_picker_returns_users_for_instructor(
    client: TestClient, db: Session
) -> None:
    lesson = _create_lesson(db)
    email = f"ws-picker-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(client=client, email=email, db=db)
    r = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{lesson.id}/roster-user-picker",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "count" in body
    assert body["count"] >= 1


def test_read_lesson_roster_user_picker_404_for_missing_lesson(
    client: TestClient, db: Session
) -> None:
    email = f"ws-picker-404-{uuid.uuid4()}@example.com"
    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password="pw123456",
            is_instructor=True,
        ),
    )
    headers = authentication_token_from_email(client=client, email=email, db=db)
    missing = uuid.uuid4()
    r = client.get(
        f"{settings.API_V1_STR}/workshop/lessons/{missing}/roster-user-picker",
        headers=headers,
    )
    assert r.status_code == 404
