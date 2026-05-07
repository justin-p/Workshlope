"""Unit tests for workshop session helpers (JWT subprotocol + handshake rules)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status
from sqlmodel import Session, select

from app import crud
from app.api.routes import workshop_sessions as ws_mod
from app.core.config import settings
from app.models import (
    Lesson,
    LessonRepo,
    SessionInstructor,
    User,
    UserCreate,
    WorkshopParticipant,
    WorkshopSession,
)


def _make_live_session_and_lesson(db: Session) -> WorkshopSession:
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


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("", None),
        ("foo", None),
        ("ticket", None),
        ("ticket,", None),
        ("wrong-protocol, token", None),
        ("ticket, abcdef", "abcdef"),
        ("ticket , z9", "z9"),
        ("ticket,z9 ", "z9"),
    ],
)
def test_extract_ws_ticket_from_subprotocols(
    header: str | None, expected: str | None
) -> None:
    assert ws_mod._extract_ws_ticket_from_subprotocols(header) == expected


def test_authorize_ws_handshake_rejects_claims_that_do_not_decode_to_uuids(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)

    claims = {
        "sid": "not-a-uuid",
        "uid": str(uuid.uuid4()),
        "role": "participant",
        "pg": 1,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_requires_route_session_matches_token(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)
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

    claims = {
        "sid": str(uuid.uuid4()),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }

    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_missing_workshop_session_row(
    db: Session,
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    fake_sid = uuid.uuid4()
    claims = {
        "sid": str(fake_sid),
        "uid": str(user.id),
        "role": "participant",
        "pg": 1,
    }

    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=fake_sid,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_non_active_session(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    session.status = "scheduled"
    db.add(session)
    db.commit()

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

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_stale_ticket_part_generation(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)
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

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": int(session.part_generation) + 99,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_inactive_user(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    user.is_active = False
    db.add(user)
    db.add(
        WorkshopParticipant(
            session_id=session.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_participant_without_seat(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_participant_not_entered(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session.id,
            user_id=user.id,
            joined_at=None,
            invited_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_soft_removed_participant(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"soft-removed-{uuid.uuid4()}@example.com",
            password=settings.FIRST_SUPERUSER_PASSWORD,
        ),
    )
    participant = WorkshopParticipant(
        session_id=session.id,
        user_id=user.id,
        joined_at=datetime.now(timezone.utc),
        removed_at=datetime.now(timezone.utc),
    )
    db.add(participant)
    db.commit()

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_unknown_role_claim(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "auditor",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_unknown_role_claim_hits_else_return(
    db: Session,
) -> None:
    """Explicit else-branch (covers role other than participant | instructor)."""
    ws_session = _make_live_session_and_lesson(db)
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"ws-role-else-{uuid.uuid4()}@example.com",
            password="pw123456",
        ),
    )
    db.commit()

    claims = {
        "sid": str(ws_session.id),
        "uid": str(user.id),
        "role": "trainer",
        "pg": ws_session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=ws_session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_allows_superuser_as_instructor_without_assignment(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)
    su = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    assert su is not None
    assert su.is_superuser is True

    claims = {
        "sid": str(session.id),
        "uid": str(su.id),
        "role": "instructor",
        "pg": session.part_generation,
    }
    handshake = ws_mod._authorize_workshop_ws_handshake(
        db,
        route_session_id=session.id,
        claims=claims,
    )
    assert handshake is not None
    assert handshake.role == "instructor"
    assert handshake.user_id == su.id


def test_authorize_ws_handshake_rejects_claims_with_invalid_pg_type(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)

    claims = {
        "sid": str(session.id),
        "uid": str(uuid.uuid4()),
        "role": "participant",
        "pg": "nah",
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_rejects_claims_missing_fields(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    claims: dict[str, object] = {"sid": str(session.id)}
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_denies_instructor_claim_when_seat_soft_removed(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"instr-removed-seat-{uuid.uuid4()}@example.com",
            password="pw123456",
            is_instructor=True,
        ),
    )
    now = datetime.now(timezone.utc)
    db.add(
        SessionInstructor(
            session_id=session.id,
            user_id=user.id,
            role="lead",
            removed_at=now,
        ),
    )
    db.commit()

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "instructor",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_denies_non_superuser_without_instructor_row(
    db: Session,
) -> None:
    session = _make_live_session_and_lesson(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    assert user.is_superuser is False

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "instructor",
        "pg": session.part_generation,
    }
    assert (
        ws_mod._authorize_workshop_ws_handshake(
            db,
            route_session_id=session.id,
            claims=claims,
        )
        is None
    )


def test_authorize_ws_handshake_happy_instructor_with_assignment(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    email = f"instr-auth-{uuid.uuid4()}@example.com"

    user_create = UserCreate(
        email=email,
        password="strongpassword!",
        full_name="Instructor Auth",
        is_instructor=True,
    )
    user = crud.create_user(session=db, user_create=user_create)
    db.refresh(user)
    db.add(
        SessionInstructor(
            session_id=session.id,
            user_id=user.id,
            role="lead",
        )
    )
    db.commit()

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "instructor",
        "pg": session.part_generation,
    }
    handshake = ws_mod._authorize_workshop_ws_handshake(
        db,
        route_session_id=session.id,
        claims=claims,
    )
    assert handshake is not None
    assert handshake.role == "instructor"


def test_authorize_ws_handshake_happy_participant(db: Session) -> None:
    session = _make_live_session_and_lesson(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    user.is_active = True
    db.add(user)
    db.add(
        WorkshopParticipant(
            session_id=session.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    claims = {
        "sid": str(session.id),
        "uid": str(user.id),
        "role": "participant",
        "pg": session.part_generation,
    }
    handshake = ws_mod._authorize_workshop_ws_handshake(
        db,
        route_session_id=session.id,
        claims=claims,
    )
    assert handshake is not None
    assert handshake.role == "participant"


def test_validate_transition_noop_when_status_unchanged() -> None:
    ws_mod._validate_workshop_session_status_transition(
        current_status="live",
        target_status="live",
    )


def test_validate_transition_raises_when_already_ended() -> None:
    with pytest.raises(HTTPException) as exc:
        ws_mod._validate_workshop_session_status_transition(
            current_status="ended",
            target_status="paused",
        )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail == "session_already_ended"


def test_validate_transition_to_live_rejects_unknown_current_status() -> None:
    with pytest.raises(HTTPException) as exc:
        ws_mod._validate_workshop_session_status_transition(
            current_status="broken",
            target_status="live",
        )
    assert exc.value.detail == "invalid_session_status_transition"


def test_validate_transition_pause_requires_live_session() -> None:
    with pytest.raises(HTTPException) as exc:
        ws_mod._validate_workshop_session_status_transition(
            current_status="scheduled",
            target_status="paused",
        )
    assert exc.value.detail == "pause_requires_live_session"


def test_validate_transition_end_requires_active_session() -> None:
    with pytest.raises(HTTPException) as exc:
        ws_mod._validate_workshop_session_status_transition(
            current_status="scheduled",
            target_status="ended",
        )
    assert exc.value.detail == "end_requires_active_session"


def test_validate_transition_accepts_allowed_paths() -> None:
    ws_mod._validate_workshop_session_status_transition(
        current_status="scheduled",
        target_status="live",
    )
    ws_mod._validate_workshop_session_status_transition(
        current_status="paused",
        target_status="live",
    )
    ws_mod._validate_workshop_session_status_transition(
        current_status="live",
        target_status="paused",
    )
    ws_mod._validate_workshop_session_status_transition(
        current_status="live",
        target_status="ended",
    )
    ws_mod._validate_workshop_session_status_transition(
        current_status="paused",
        target_status="ended",
    )


def test_validate_transition_rejects_unknown_target_status() -> None:
    with pytest.raises(HTTPException) as exc:
        ws_mod._validate_workshop_session_status_transition(
            current_status="live",
            target_status="scheduled",
        )
    assert exc.value.detail == "invalid_session_status_transition"


def test_timer_public_returns_inactive_placeholder_when_state_missing() -> None:
    sid = uuid.uuid4()
    out = ws_mod._timer_public(sid, None)
    assert out.status == "inactive"
    assert out.session_id == sid


def test_timer_public_countdown_computes_elapsed_and_remaining() -> None:
    sid = uuid.uuid4()
    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    state = SimpleNamespace(
        status="running",
        mode="countdown",
        target_seconds=30,
        started_at=started,
        paused_at=None,
    )
    out = ws_mod._timer_public(sid, state)
    assert out.elapsed_seconds is not None and out.elapsed_seconds >= 5
    assert out.remaining_seconds is not None
    assert out.remaining_seconds <= 25


def test_workshop_session_detail_shared_returns_fallback_when_lesson_row_missing() -> (
    None
):
    lesson_id = uuid.uuid4()
    session_id = uuid.uuid4()
    mock_db = MagicMock()

    def _get_side(model: type, pk: uuid.UUID) -> object | None:
        if model is Lesson and pk == lesson_id:
            return None
        raise AssertionError("unexpected Session.get invocation")

    mock_db.get.side_effect = _get_side
    ws_row = WorkshopSession(
        id=session_id,
        lesson_id=lesson_id,
        status="live",
        created_at=datetime.now(timezone.utc),
    )

    core, lesson_summary, parts = ws_mod._workshop_session_detail_shared(
        mock_db, workshop_row=ws_row
    )
    assert core.id == session_id
    assert lesson_summary.id == lesson_id
    assert lesson_summary.title == "Lesson unavailable"
    assert lesson_summary.lesson_repo_health == "unhealthy"
    assert lesson_summary.lesson_content_available is False
    assert lesson_summary.lesson_content_issue == "lesson_missing"
    assert parts == []


def test_timer_public_paused_uses_paused_at_for_elapsed_cap() -> None:
    sid = uuid.uuid4()
    started = datetime.now(timezone.utc) - timedelta(seconds=100)
    paused_at = started + timedelta(seconds=12)
    state = SimpleNamespace(
        status="paused",
        mode="countup",
        target_seconds=None,
        started_at=started,
        paused_at=paused_at,
    )
    out = ws_mod._timer_public(sid, state)
    assert out.elapsed_seconds == 12
