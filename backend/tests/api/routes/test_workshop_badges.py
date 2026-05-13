import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Lesson,
    LessonRepo,
    SessionInstructor,
    User,
    WorkshopBadgeDefinition,
    WorkshopBadgeGrant,
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


def test_badge_catalog_includes_lesson_repo_id_for_lesson_badges(
    client: TestClient,
    db: Session,
) -> None:
    headers, _ = _instructor_headers(client, db)
    session_row = _create_live_session(db)
    lesson = db.get(Lesson, session_row.lesson_id)
    assert lesson is not None
    badge = WorkshopBadgeDefinition(
        slug=f"{lesson.slug}__finisher",
        title="Finisher",
        points=3,
        lesson_id=lesson.id,
    )
    db.add(badge)
    db.commit()
    db.refresh(badge)

    listed = client.get(f"{settings.API_V1_STR}/workshop/badges", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["data"]
    match = next((r for r in rows if r["id"] == str(badge.id)), None)
    assert match is not None
    assert match["lesson_repo_id"] == str(lesson.repo_id)


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
            "lesson_id": str(session_row.lesson_id),
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

    detail = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
    )
    assert detail.status_code == 200
    djson = detail.json()
    assert djson["view"] == "instructor"
    active = djson["active_badge_grants"]
    assert len(active) == 1
    assert active[0]["user_id"] == str(trainee.id)
    assert active[0]["badge_id"] == badge_id
    assert active[0]["slug"] == create.json()["slug"]

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

    detail_after = client.get(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}",
        headers=headers,
    )
    assert detail_after.status_code == 200
    assert detail_after.json()["active_badge_grants"] == []

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
            "lesson_id": str(session_row.lesson_id),
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
            "lesson_id": str(session_row.lesson_id),
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


def test_read_and_patch_workshop_badge(client: TestClient, db: Session) -> None:
    headers, _ = _instructor_headers(client, db)
    slug = f"badge-edit-{uuid.uuid4().hex}"
    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={"slug": slug, "title": "Before", "points": 3, "description": "d0"},
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]

    missing = client.get(
        f"{settings.API_V1_STR}/workshop/badges/{uuid.uuid4()}",
        headers=headers,
    )
    assert missing.status_code == 404

    got = client.get(
        f"{settings.API_V1_STR}/workshop/badges/{badge_id}",
        headers=headers,
    )
    assert got.status_code == 200
    assert got.json()["title"] == "Before"
    assert got.json()["points"] == 3

    patched = client.patch(
        f"{settings.API_V1_STR}/workshop/badges/{badge_id}",
        headers=headers,
        json={"title": "After", "points": 7, "description": "d1", "slug": slug},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "After"
    assert patched.json()["points"] == 7
    assert patched.json()["description"] == "d1"


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
            "lesson_id": str(session_row.lesson_id),
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
        json={
            "slug": f"m-{uuid.uuid4().hex}",
            "title": "T",
            "points": 1,
            "lesson_id": str(session_row.lesson_id),
        },
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
        json={
            "slug": f"rev-{uuid.uuid4().hex}",
            "title": "R",
            "points": 3,
            "lesson_id": str(session_row.lesson_id),
        },
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


def test_org_grant_and_global_leaderboard(client: TestClient, db: Session) -> None:
    headers, instructor = _instructor_headers(client, db)
    trainee_email = f"org-lb-{uuid.uuid4()}@example.com"
    trainee_headers = authentication_token_from_email(
        client=client, email=trainee_email, db=db
    )
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None

    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"org-badge-{uuid.uuid4().hex}",
            "title": "Org only",
            "points": 7,
        },
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]

    grant = client.post(
        f"{settings.API_V1_STR}/workshop/badges/org/grant",
        headers=headers,
        json={"user_id": str(trainee.id), "badge_id": badge_id},
    )
    assert grant.status_code == 200

    dup = client.post(
        f"{settings.API_V1_STR}/workshop/badges/org/grant",
        headers=headers,
        json={"user_id": str(trainee.id), "badge_id": badge_id},
    )
    assert dup.status_code == 409

    global_lb = client.get(
        f"{settings.API_V1_STR}/workshop/badges/leaderboard",
        headers=trainee_headers,
    )
    assert global_lb.status_code == 200
    body = global_lb.json()
    assert body["count"] >= 1
    row = next(r for r in body["data"] if r["user_id"] == str(trainee.id))
    assert "email" not in row
    assert row["total_points"] == 7
    assert row["badge_count"] == 1
    assert row["rank"] >= 1

    user_badges = client.get(
        f"{settings.API_V1_STR}/workshop/badges/leaderboard/users/{trainee.id}/badges",
        headers=trainee_headers,
    )
    assert user_badges.status_code == 200
    ub = user_badges.json()
    assert ub["count"] == 1
    assert ub["data"][0]["title"] == "Org only"
    assert ub["data"][0]["slug"].startswith("org-badge-")
    assert ub["data"][0]["points"] == 7

    revoke = client.post(
        f"{settings.API_V1_STR}/workshop/badges/org/revoke",
        headers=headers,
        json={
            "user_id": str(trainee.id),
            "badge_id": badge_id,
            "reason": "test cleanup",
        },
    )
    assert revoke.status_code == 200

    user_badges_after = client.get(
        f"{settings.API_V1_STR}/workshop/badges/leaderboard/users/{trainee.id}/badges",
        headers=trainee_headers,
    )
    assert user_badges_after.status_code == 200
    assert user_badges_after.json()["count"] == 0

    after = client.get(
        f"{settings.API_V1_STR}/workshop/badges/leaderboard",
        headers=trainee_headers,
    )
    assert after.status_code == 200
    ids = {r["user_id"] for r in after.json()["data"]}
    assert str(trainee.id) not in ids


def test_global_leaderboard_user_badges_empty_when_none(
    client: TestClient, db: Session
) -> None:
    headers, _ = _instructor_headers(client, db)
    uid = uuid.uuid4()
    r = client.get(
        f"{settings.API_V1_STR}/workshop/badges/leaderboard/users/{uid}/badges",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["data"] == []


def test_org_grant_requires_instructor(client: TestClient, db: Session) -> None:
    trainee_email = f"org-denied-{uuid.uuid4()}@example.com"
    th = authentication_token_from_email(client=client, email=trainee_email, db=db)
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None
    r = client.post(
        f"{settings.API_V1_STR}/workshop/badges/org/grant",
        headers=th,
        json={"user_id": str(trainee.id), "badge_id": str(uuid.uuid4())},
    )
    assert r.status_code == 403


def test_hub_badge_grant_and_revoke_paths(client: TestClient, db: Session) -> None:
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
    lesson = db.get(Lesson, session_row.lesson_id)
    assert lesson is not None
    badge = WorkshopBadgeDefinition(
        slug=f"hub-path-{uuid.uuid4()}",
        title="Hub path",
        points=4,
        lesson_id=lesson.id,
    )
    db.add(badge)
    db.commit()
    db.refresh(badge)

    trainee_email = f"hub-trainee-{uuid.uuid4()}@example.com"
    authentication_token_from_email(client=client, email=trainee_email, db=db)
    trainee = db.exec(select(User).where(User.email == trainee_email)).first()
    assert trainee is not None

    grant = client.post(
        f"{settings.API_V1_STR}/workshop/badges/{badge.id}/grants",
        headers=headers,
        json={"user_id": str(trainee.id)},
    )
    assert grant.status_code == 200

    rec = client.get(
        f"{settings.API_V1_STR}/workshop/badges/{badge.id}/grants",
        headers=headers,
    )
    assert rec.status_code == 200
    assert rec.json()["count"] == 1

    revoke = client.post(
        f"{settings.API_V1_STR}/workshop/badges/{badge.id}/grants/revoke",
        headers=headers,
        json={"user_id": str(trainee.id), "reason": "cleanup"},
    )
    assert revoke.status_code == 200
    rec2 = client.get(
        f"{settings.API_V1_STR}/workshop/badges/{badge.id}/grants",
        headers=headers,
    )
    assert rec2.json()["count"] == 0


def test_session_end_auto_awards_lesson_badges(client: TestClient, db: Session) -> None:
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
    lesson = db.get(Lesson, session_row.lesson_id)
    assert lesson is not None
    badge = WorkshopBadgeDefinition(
        slug=f"auto-{uuid.uuid4()}",
        title="Auto badge",
        points=7,
        lesson_id=lesson.id,
    )
    db.add(badge)
    trainee_email = f"auto-trainee-{uuid.uuid4()}@example.com"
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
    db.refresh(badge)

    end = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
        headers=headers,
    )
    assert end.status_code == 200

    active = db.exec(
        select(WorkshopBadgeGrant).where(
            WorkshopBadgeGrant.badge_id == badge.id,
            WorkshopBadgeGrant.user_id == trainee.id,
            col(WorkshopBadgeGrant.revoked_at).is_(None),
        )
    ).first()
    assert active is not None
    assert active.session_id == session_row.id

    end2 = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
        headers=headers,
    )
    assert end2.status_code == 403

    rows = db.exec(
        select(WorkshopBadgeGrant).where(WorkshopBadgeGrant.badge_id == badge.id)
    ).all()
    assert len([r for r in rows if r.revoked_at is None]) == 1


# 1×1 PNG (valid magic bytes + structure)
_MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200010000010802000000907753de"
    "0000000c49444154789c63f8cfc000000301010018dd8db40000000049454e44ae426082"
)


def test_workshop_badge_catalog_requires_auth(client: TestClient) -> None:
    r = client.get(f"{settings.API_V1_STR}/workshop/badges")
    assert r.status_code == 401


def test_workshop_badge_image_get_anonymous_returns_png_bytes(
    client: TestClient, db: Session
) -> None:
    headers, _ = _instructor_headers(client, db)
    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-img-{uuid.uuid4()}",
            "title": "Image test",
            "points": 1,
        },
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]

    up = client.post(
        f"{settings.API_V1_STR}/workshop/badges/{badge_id}/image",
        headers=headers,
        files={"file": ("t.png", _MINIMAL_PNG, "image/png")},
    )
    assert up.status_code == 200, up.text

    anon = client.get(f"{settings.API_V1_STR}/workshop/badges/{badge_id}/image")
    assert anon.status_code == 200
    assert anon.headers.get("content-type", "").startswith("image/png")
    assert anon.content.startswith(b"\x89PNG\r\n\x1a\n")

    with_auth = client.get(
        f"{settings.API_V1_STR}/workshop/badges/{badge_id}/image",
        headers=headers,
    )
    assert with_auth.status_code == 200
    assert with_auth.content == anon.content


def test_workshop_badge_image_not_found_unknown_badge(client: TestClient) -> None:
    missing = uuid.uuid4()
    r = client.get(f"{settings.API_V1_STR}/workshop/badges/{missing}/image")
    assert r.status_code == 404


def test_workshop_badge_image_not_found_when_no_upload(
    client: TestClient, db: Session
) -> None:
    headers, _ = _instructor_headers(client, db)
    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-noimg-{uuid.uuid4()}",
            "title": "No image",
            "points": 1,
        },
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]
    r = client.get(f"{settings.API_V1_STR}/workshop/badges/{badge_id}/image")
    assert r.status_code == 404


def test_list_badges_includes_image_url_after_upload(
    client: TestClient, db: Session
) -> None:
    headers, _ = _instructor_headers(client, db)
    create = client.post(
        f"{settings.API_V1_STR}/workshop/badges",
        headers=headers,
        json={
            "slug": f"badge-url-{uuid.uuid4()}",
            "title": "URL field",
            "points": 2,
        },
    )
    assert create.status_code == 200
    badge_id = create.json()["id"]
    assert create.json().get("image_url") is None

    up = client.post(
        f"{settings.API_V1_STR}/workshop/badges/{badge_id}/image",
        headers=headers,
        files={"file": ("t.png", _MINIMAL_PNG, "image/png")},
    )
    assert up.status_code == 200

    listed = client.get(f"{settings.API_V1_STR}/workshop/badges", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["data"]
    row = next((x for x in rows if x["id"] == badge_id), None)
    assert row is not None
    assert row.get("image_url") is not None
    assert f"/workshop/badges/{badge_id}/image" in row["image_url"]
