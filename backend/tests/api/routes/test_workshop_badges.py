import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Lesson,
    LessonRepo,
    SessionInstructor,
    User,
    WorkshopParticipant,
    WorkshopSession,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


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
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=trainee.id,
        )
    )
    db.commit()

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

    duplicate_grant = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
        headers=headers,
        json={"user_id": str(trainee.id), "badge_id": badge_id},
    )
    assert duplicate_grant.status_code == 409
    assert duplicate_grant.json()["detail"] == "badge_already_granted"

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

    revoke_retry = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={
            "user_id": str(trainee.id),
            "badge_id": badge_id,
            "reason": "repeat retry",
        },
    )
    assert revoke_retry.status_code == 200
    assert revoke_retry.json()["message"] == "Badge already revoked"

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


def test_revoke_requires_non_empty_reason(client: TestClient, db: Session) -> None:
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
    authentication_token_from_email(client=client, email=trainee_email, db=db)
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=trainee.id,
        )
    )
    db.commit()

    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-{uuid.uuid4()}",
            "title": "Reason required",
            "points": 1,
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

    missing_reason = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={"user_id": str(trainee.id), "badge_id": badge_id},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["detail"] == "badge_revoke_reason_required"

    blank_reason = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={
            "user_id": str(trainee.id),
            "badge_id": badge_id,
            "reason": "   ",
        },
    )
    assert blank_reason.status_code == 422
    assert blank_reason.json()["detail"] == "badge_revoke_reason_required"

    valid_reason = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={
            "user_id": str(trainee.id),
            "badge_id": badge_id,
            "reason": "  policy mismatch  ",
        },
    )
    assert valid_reason.status_code == 200


def test_revoke_returns_404_when_session_not_found(
    client: TestClient, db: Session
) -> None:
    headers, _ = _instructor_headers(client, db)
    missing = uuid.uuid4()
    r = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{missing}/revoke",
        headers=headers,
        json={
            "user_id": str(uuid.uuid4()),
            "badge_id": str(uuid.uuid4()),
            "reason": "session vanished",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


def test_grant_requires_participant_roster_membership(
    client: TestClient, db: Session
) -> None:
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

    outsider_email = f"badge-outsider-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=outsider_email, db=db)
    outsider = db.exec(select(User).where(User.email == outsider_email)).first()
    assert outsider is not None

    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-{uuid.uuid4()}",
            "title": "Roster only",
            "points": 2,
        },
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]

    denied = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
        headers=headers,
        json={"user_id": str(outsider.id), "badge_id": badge_id},
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "Participant not in session roster"


def test_create_badge_rejects_duplicate_slug(client: TestClient, db: Session) -> None:
    headers, _ = _instructor_headers(client, db)
    slug = f"badge-dup-{uuid.uuid4().hex}"
    body = {"slug": slug, "title": "One", "points": 1}
    assert (
        client.post(
            f"{settings.API_V1_STR}/workshop/badges", headers=headers, json=body
        ).status_code
        == 200
    )
    conflict = client.post(
        f"{settings.API_V1_STR}/workshop/badges", headers=headers, json=body
    )
    assert conflict.status_code == 409


def test_superuser_grant_bypasses_session_instructor_check(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    su_headers = get_superuser_token_headers(client)

    trainee_email = f"b-su-trainee-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=trainee_email, db=db)
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=trainee.id))
    db.commit()

    badge = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=su_headers,
        json={
            "slug": f"b-su-{uuid.uuid4().hex}",
            "title": "Hero",
            "points": 2,
        },
    )
    assert badge.status_code == 200

    granted = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
        headers=su_headers,
        json={"user_id": str(trainee.id), "badge_id": badge.json()["id"]},
    )
    assert granted.status_code == 200


def test_grant_and_leaderboard_requires_valid_ids(
    client: TestClient, db: Session
) -> None:
    headers, instructor = _instructor_headers(client, db)
    trainee_email = f"b-miss-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=trainee_email, db=db)
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None
    session_row = _create_live_session(db)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        ),
    )
    db.add(
        WorkshopParticipant(session_id=session_row.id, user_id=trainee.id),
    )
    db.commit()

    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={"slug": f"m-{uuid.uuid4().hex}", "title": "T", "points": 1},
    )
    bid = create.json()["id"]

    bogus_session = uuid.uuid4()
    assert (
        client.post(
            f"{settings.API_V1_STR}/workshop/badges/sessions/{bogus_session}/grant",
            headers=headers,
            json={"user_id": str(trainee.id), "badge_id": bid},
        ).status_code
        == 404
    )

    bogus_badge = uuid.uuid4()
    assert (
        client.post(
            f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
            headers=headers,
            json={"user_id": str(trainee.id), "badge_id": str(bogus_badge)},
        ).status_code
        == 404
    )

    board = client.get(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{bogus_session}/leaderboard",
        headers=headers,
    )
    assert board.status_code == 404


def test_revoke_grant_lifecycle_edges(client: TestClient, db: Session) -> None:
    headers, instructor = _instructor_headers(client, db)
    session_row = _create_live_session(db)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor.id,
            role="lead",
        ),
    )
    db.commit()
    trainee_email = f"b-rev-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=trainee_email, db=db)
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None
    db.add(WorkshopParticipant(session_id=session_row.id, user_id=trainee.id))
    db.commit()

    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={"slug": f"rev-{uuid.uuid4().hex}", "title": "R", "points": 3},
    )
    bid = create.json()["id"]
    payload = {"user_id": str(trainee.id), "badge_id": bid}

    missing_grant = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={
            "user_id": str(trainee.id),
            "badge_id": str(uuid.uuid4()),
            "reason": "n/a",
        },
    )
    assert missing_grant.status_code == 404

    assert (
        client.post(
            f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
            headers=headers,
            json=payload,
        ).status_code
        == 200
    )
    revoke = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={**payload, "reason": "policy"},
    )
    assert revoke.status_code == 200

    regrant = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/grant",
        headers=headers,
        json=payload,
    )
    assert regrant.status_code == 200

    second_revoke = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={**payload, "reason": "cleanup"},
    )
    assert second_revoke.status_code == 200

    idempotent = client.post(
        f"{settings.API_V1_STR}/workshop/badges/sessions/{session_row.id}/revoke",
        headers=headers,
        json={**payload, "reason": "again"},
    )
    assert idempotent.status_code == 200
    assert idempotent.json()["message"] == "Badge already revoked"
