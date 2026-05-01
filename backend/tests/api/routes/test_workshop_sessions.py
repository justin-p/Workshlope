import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import (
    Lesson,
    LessonPart,
    LessonRepo,
    SessionInstructor,
    User,
    WorkshopParticipant,
    WorkshopSession,
)
from app.services import workshop_realtime as workshop_realtime_mod
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


def _add_two_parts_to_session_lesson(db: Session, session: WorkshopSession) -> None:
    lesson = db.get(Lesson, session.lesson_id)
    assert lesson is not None
    db.add(
        LessonPart(
            lesson_id=lesson.id,
            ordering=0,
            slug=f"part-0-{uuid.uuid4()}",
            title="Part 0",
            path="01-part-0.md",
            body_md="# Part 0",
        )
    )
    db.add(
        LessonPart(
            lesson_id=lesson.id,
            ordering=1,
            slug=f"part-1-{uuid.uuid4()}",
            title="Part 1",
            path="02-part-1.md",
            body_md="# Part 1",
        )
    )
    db.commit()


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


def test_enter_rejected_when_session_ended(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "ended"
    db.add(session_row)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Session has ended"


def test_ws_ticket_rejected_when_session_ended(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    session_row.status = "ended"
    db.add(session_row)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Session has ended"


def test_http_start_requires_instructor_role(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
        headers=normal_user_token_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "User is not an instructor for this session"


def test_http_start_scheduled_then_ws_ticket_allowed(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    instructor_email = f"instr-start-{uuid.uuid4()}@example.com"
    inst_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    inst_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert inst_user is not None
    inst_user.is_instructor = True
    db.add(inst_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=inst_user.id,
            role="lead",
        )
    )
    participant_email = f"participant-start-{uuid.uuid4()}@example.com"
    p_headers = authentication_token_from_email(
        client=client, email=participant_email, db=db
    )
    p_user = db.exec(select(User).where(User.email == participant_email)).first()
    assert p_user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=p_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    start = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
        headers=inst_headers,
    )
    assert start.status_code == 200
    assert start.json()["message"] == "Session started"

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=p_headers,
    )
    assert ticket.status_code == 200


def test_http_second_start_rejected(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()
    instructor_email = f"i2-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    assert (
        client.post(
            f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
            headers=i_headers,
        ).status_code
        == 200
    )
    again = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/start",
        headers=i_headers,
    )
    assert again.status_code == 403
    assert again.json()["detail"] == "start_requires_scheduled_session"


def test_http_end_broadcast_blocked_when_scheduled(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()
    instructor_email = f"i3-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
        headers=i_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "end_requires_active_session"


def test_ws_connect_ticket_rejected_after_session_end(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )

    instructor_email = f"i-end-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    end_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
        headers=i_headers,
    )
    assert end_resp.status_code == 200

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_live_status_rejected_after_session_http_end(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    instructor_email = f"i-live-end-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"
        assert (
            client.post(
                f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/end",
                headers=i_headers,
            ).status_code
            == 200
        )
        ended_push = trainee_ws.receive_json()
        assert ended_push == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "ended",
        }
        trainee_ws.send_json({"type": "live_status", "live_status": "done"})
        denied = trainee_ws.receive_json()

    assert denied == {"type": "error", "detail": "session_not_active"}


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


def _workshop_ws_path(session_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/workshop/sessions/{session_id}/ws"


def test_ws_connect_accepts_ticket_subprotocol(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    assert ticket_resp.status_code == 200
    ticket = ticket_resp.json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as websocket:
        assert websocket.accepted_subprotocol == "ticket"
        hello = websocket.receive_json()
        assert hello["type"] == "session.connected"
        assert hello["session_id"] == str(session_row.id)
        assert hello["role"] == "participant"
        assert hello["part_generation"] == session_row.part_generation


def test_ws_connect_denies_without_ticket_marker(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    ticket = ticket_resp.json()["ticket"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=[ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_connect_denies_stale_part_generation(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    session_row.part_generation = 5
    db.add(session_row)
    db.commit()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    stale_ticket = jwt.encode(
        {
            "sid": str(session_row.id),
            "uid": str(user.id),
            "role": "participant",
            "pg": 1,
            "aud": "workshop-ws",
            "exp": expires_at,
        },
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", stale_ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_connect_denies_session_path_mismatch(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    other_session = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    ticket = ticket_resp.json()["ticket"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(other_session.id),
            subprotocols=["ticket", ticket],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_participant_live_status_persists_ack_and_fanout_registered(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    participant_row = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(participant_row)
    db.commit()
    db.refresh(participant_row)
    assert participant_row.live_status == "busy"

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket_resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    )
    ticket = ticket_resp.json()["ticket"]

    published: list[tuple[uuid.UUID, uuid.UUID, str]] = []

    async def capture_publish(
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        live_status: str,
    ) -> None:
        published.append((session_id, user_id, live_status))

    monkeypatch.setattr(
        workshop_realtime_mod.workshop_hub,
        "publish_participant_live_status",
        capture_publish,
    )

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.connected"
        websocket.send_json({"type": "live_status", "live_status": "done"})
        ack = websocket.receive_json()
        assert ack == {"type": "live_status.ack", "live_status": "done"}

    db.refresh(participant_row)
    assert participant_row.live_status == "done"
    assert published == [(session_row.id, user.id, "done")]


def test_ws_rejects_when_db_part_generation_runs_ahead_of_connection_mirror(
    client: TestClient,
    db: Session,
) -> None:
    """If DB part_generation moves without mirroring into the hub connections, the
    next inbound frame is rejected so the client must mint a fresh ws-ticket."""
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        ws_row = db.get(WorkshopSession, session_row.id)
        assert ws_row is not None
        ws_row.part_generation = int(ws_row.part_generation) + 1
        db.add(ws_row)
        db.commit()
        expected_gen = int(ws_row.part_generation)

        ws.send_json({"type": "live_status", "live_status": "done"})
        err = ws.receive_json()

    assert err == {
        "type": "error",
        "detail": "part_generation_stale",
        "part_generation": expected_gen,
    }


def test_ws_instructor_can_advance_part_and_broadcast_to_participants(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    participant_user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert participant_user is not None
    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=participant_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    participant_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]
    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", participant_ticket],
    ) as participant_ws:
        assert participant_ws.receive_json()["type"] == "session.connected"
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket],
        ) as instructor_ws:
            assert instructor_ws.receive_json()["type"] == "session.connected"
            instructor_ws.send_json({"type": "part.advance", "part_index": 1})
            ack = instructor_ws.receive_json()
            broadcast = participant_ws.receive_json()

    assert ack["type"] == "part.advance.ack"
    assert ack["part_index"] == 1
    assert broadcast["type"] == "session.part_changed"
    assert broadcast["part_index"] == 1


def test_ws_part_advance_denied_when_session_paused(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    session_row.status = "paused"
    db.add(session_row)
    db.commit()

    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", instructor_ticket],
    ) as instructor_ws:
        assert instructor_ws.receive_json()["type"] == "session.connected"
        instructor_ws.send_json({"type": "part.advance", "part_index": 1})
        denied = instructor_ws.receive_json()

    assert denied == {
        "type": "error",
        "detail": "advance_requires_live_session",
    }


def test_ws_participant_live_status_rejected_when_session_paused(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    participant_user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert participant_user is not None

    instructor_email = f"instructor-pause-ls-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=participant_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    participant_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]
    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", participant_ticket],
    ) as participant_ws:
        assert participant_ws.receive_json()["type"] == "session.connected"
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket],
        ) as instructor_ws:
            assert instructor_ws.receive_json()["type"] == "session.connected"
            instructor_ws.send_json({"type": "session.pause"})
            assert instructor_ws.receive_json() == {
                "type": "session.pause.ack",
                "status": "paused",
            }
            assert instructor_ws.receive_json() == {
                "type": "session.status_changed",
                "session_id": str(session_row.id),
                "status": "paused",
            }
        assert participant_ws.receive_json() == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "paused",
        }
        participant_ws.send_json({"type": "live_status", "live_status": "done"})
        denied = participant_ws.receive_json()

    assert denied == {
        "type": "error",
        "detail": "live_status_requires_live_session",
    }


def test_ws_instructor_pause_resume_broadcasts_status(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    participant_headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    participant_user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert participant_user is not None

    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=participant_user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    assert session_row.status == "live"

    participant_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]
    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", participant_ticket],
    ) as participant_ws:
        assert participant_ws.receive_json()["type"] == "session.connected"

        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket],
        ) as instructor_ws:
            assert instructor_ws.receive_json()["type"] == "session.connected"
            instructor_ws.send_json({"type": "session.pause"})
            pause_ack = instructor_ws.receive_json()
            pause_broadcast = participant_ws.receive_json()

        assert pause_ack == {"type": "session.pause.ack", "status": "paused"}
        assert pause_broadcast == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "paused",
        }

        db.refresh(session_row)
        assert session_row.status == "paused"

        instructor_ticket_resume = client.post(
            f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
            headers=instructor_headers,
        ).json()["ticket"]

        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", instructor_ticket_resume],
        ) as instructor_resume_ws:
            assert instructor_resume_ws.receive_json()["type"] == "session.connected"
            instructor_resume_ws.send_json({"type": "session.resume"})
            resume_ack = instructor_resume_ws.receive_json()
            resume_broadcast = participant_ws.receive_json()

        assert resume_ack == {"type": "session.resume.ack", "status": "live"}
        assert resume_broadcast == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "live",
        }

    db.refresh(session_row)
    assert session_row.status == "live"


def test_ws_second_pause_rejected(
    client: TestClient,
    db: Session,
) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"instructor-{uuid.uuid4()}@example.com"
    instructor_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.commit()

    instructor_ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=instructor_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", instructor_ticket],
    ) as instructor_ws:
        assert instructor_ws.receive_json()["type"] == "session.connected"
        instructor_ws.send_json({"type": "session.pause"})
        assert instructor_ws.receive_json() == {
            "type": "session.pause.ack",
            "status": "paused",
        }
        assert instructor_ws.receive_json() == {
            "type": "session.status_changed",
            "session_id": str(session_row.id),
            "status": "paused",
        }
        instructor_ws.send_json({"type": "session.pause"})
        denied = instructor_ws.receive_json()

    assert denied == {
        "type": "error",
        "detail": "pause_requires_live_session",
    }


def test_http_workshop_enter_start_end_ticket_return_404_for_unknown_session_id(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    missing = uuid.uuid4()
    for suffix in ("enter", "start", "end", "ws-ticket"):
        r = client.post(
            f"{settings.API_V1_STR}/workshop/sessions/{missing}/{suffix}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "Session not found"


def test_http_ws_ticket_403_when_rostered_but_never_entered_live_session(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            invited_at=datetime.now(timezone.utc),
            joined_at=None,
        )
    )
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "User must enter session first"


def test_http_enter_sets_joined_at_when_invited_but_not_entered(
    client: TestClient, db: Session, normal_user_token_headers: dict[str, str]
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    participant = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        invited_at=datetime.now(timezone.utc),
        joined_at=None,
    )
    db.add(participant)
    db.commit()

    r = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 200

    db.refresh(participant)
    assert participant.joined_at is not None


def test_http_ws_ticket_allows_superuser_as_instructor_without_assignment(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=get_superuser_token_headers(client),
    )
    assert resp.status_code == 200

    decoded = jwt.decode(
        resp.json()["ticket"],
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        audience="workshop-ws",
    )
    assert decoded["role"] == "instructor"


def test_ws_rejects_truncated_ticket_for_pyjwt_error(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _workshop_ws_path(session_row.id),
            subprotocols=["ticket", "this-is-not-three-jwt-segments"],
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_reports_invalid_json_and_invalid_message_shapes(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.connected"
        websocket.send_text("{")
        assert websocket.receive_json() == {"type": "error", "detail": "invalid_json"}

        websocket.send_text("[]")
        assert websocket.receive_json() == {
            "type": "error",
            "detail": "invalid_message",
        }

        websocket.send_json({"type": "__unknown_xyz__"})
        assert websocket.receive_json() == {
            "type": "error",
            "detail": "unknown_message_type",
        }


def test_ws_instructor_cannot_publish_live_status(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    instructor_email = f"i-ls-ban-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.commit()

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"
        ws.send_json({"type": "live_status", "live_status": "done"})
        assert ws.receive_json() == {"type": "error", "detail": "forbidden"}


def test_ws_trainee_cannot_advance_pause_or_resume(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"

        trainee_ws.send_json({"type": "part.advance", "part_index": 0})
        assert trainee_ws.receive_json() == {"type": "error", "detail": "forbidden"}

        trainee_ws.send_json({"type": "session.pause"})
        assert trainee_ws.receive_json() == {"type": "error", "detail": "forbidden"}

        trainee_ws.send_json({"type": "session.resume"})
        assert trainee_ws.receive_json() == {"type": "error", "detail": "forbidden"}


def test_ws_live_status_validation_errors_before_db(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    headers = authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        ws.send_json({"type": "live_status", "live_status": 123})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_live_status"}

        ws.send_json({"type": "live_status", "live_status": "nope"})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_live_status"}


def test_ws_part_advance_requires_integer_part_index(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)
    instructor_email = f"i-idx-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.commit()

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        ws.send_json({"type": "part.advance", "part_index": "0"})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_part_index"}

        ws.send_json({"type": "part.advance", "part_index": -1})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_part_index"}

        ws.send_json({"type": "part.advance", "part_index": 99})
        assert ws.receive_json() == {"type": "error", "detail": "invalid_part_index"}


def test_http_enter_creates_participant_when_user_not_rostered_yet(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)

    trainee_email = f"walk-in-{uuid.uuid4()}@example.com"
    headers = authentication_token_from_email(client=client, email=trainee_email, db=db)
    user = db.exec(select(User).where(User.email == trainee_email)).first()
    assert user is not None

    prior = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == user.id,
        )
    ).first()
    assert prior is None

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/enter",
        headers=headers,
    )
    assert resp.status_code == 200

    rostered = db.exec(
        select(WorkshopParticipant).where(
            WorkshopParticipant.session_id == session_row.id,
            WorkshopParticipant.user_id == user.id,
        )
    ).first()
    assert rostered is not None
    assert rostered.joined_at is not None


def test_http_ws_ticket_rejects_when_session_scheduled(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    session_row.status = "scheduled"
    db.add(session_row)
    db.commit()

    instructor_email = f"scheduled-ticket-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    i_user = db.exec(select(User).where(User.email == instructor_email)).first()
    assert i_user is not None
    i_user.is_instructor = True
    db.add(i_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=i_user.id,
            role="lead",
        )
    )
    db.commit()

    resp = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Session not started yet"


def test_ws_snap_reports_session_deleted_for_non_advance_frames(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    participant_email = f"snap-delete-{uuid.uuid4()}@example.com"
    participant_headers = authentication_token_from_email(
        client=client, email=participant_email, db=db
    )
    user = db.exec(select(User).where(User.email == participant_email)).first()
    assert user is not None
    db.add(
        WorkshopParticipant(
            session_id=session_row.id,
            user_id=user.id,
            joined_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"

        row = db.get(WorkshopSession, session_row.id)
        assert row is not None
        sid = session_row.id
        db.delete(row)
        db.commit()

        trainee_ws.send_json({"type": "live_status", "live_status": "done"})
        err = trainee_ws.receive_json()

    assert err == {"type": "error", "detail": "session_not_found"}
    assert db.get(WorkshopSession, sid) is None


def test_ws_live_status_errors_when_participant_soft_removed_mid_socket(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    participant_email = f"soft-rem-ws-{uuid.uuid4()}@example.com"
    participant_headers = authentication_token_from_email(
        client=client, email=participant_email, db=db
    )
    user = db.exec(select(User).where(User.email == participant_email)).first()
    assert user is not None
    roster = WorkshopParticipant(
        session_id=session_row.id,
        user_id=user.id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(roster)
    db.commit()
    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=participant_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as trainee_ws:
        assert trainee_ws.receive_json()["type"] == "session.connected"

        db.refresh(roster)
        roster.removed_at = datetime.now(timezone.utc)
        db.add(roster)
        db.commit()

        trainee_ws.send_json({"type": "live_status", "live_status": "done"})
        err = trainee_ws.receive_json()

    assert err == {"type": "error", "detail": "participant_not_found"}


def test_ws_part_advance_reports_session_not_found_when_row_deleted_skip_snap(
    client: TestClient, db: Session
) -> None:
    session_row = _create_live_session(db)
    _add_two_parts_to_session_lesson(db, session_row)

    instructor_email = f"i-del-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.commit()

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as ws:
        assert ws.receive_json()["type"] == "session.connected"

        row = db.get(WorkshopSession, session_row.id)
        assert row is not None
        sid = session_row.id
        db.delete(row)
        db.commit()

        ws.send_json({"type": "part.advance", "part_index": 0})
        err = ws.receive_json()

    assert err == {"type": "error", "detail": "session_not_found"}
    assert db.get(WorkshopSession, sid) is None


def test_ws_resume_requires_paused_session(client: TestClient, db: Session) -> None:
    session_row = _create_live_session(db)

    instructor_email = f"i-resume-{uuid.uuid4()}@example.com"
    i_headers = authentication_token_from_email(
        client=client, email=instructor_email, db=db
    )
    instructor_user = db.exec(
        select(User).where(User.email == instructor_email)
    ).first()
    assert instructor_user is not None
    instructor_user.is_instructor = True
    db.add(instructor_user)
    db.add(
        SessionInstructor(
            session_id=session_row.id,
            user_id=instructor_user.id,
            role="lead",
        )
    )
    db.commit()

    ticket = client.post(
        f"{settings.API_V1_STR}/workshop/sessions/{session_row.id}/ws-ticket",
        headers=i_headers,
    ).json()["ticket"]

    with client.websocket_connect(
        _workshop_ws_path(session_row.id),
        subprotocols=["ticket", ticket],
    ) as instructor_ws:
        assert instructor_ws.receive_json()["type"] == "session.connected"
        instructor_ws.send_json({"type": "session.resume"})
        err = instructor_ws.receive_json()

    assert err == {
        "type": "error",
        "detail": "resume_requires_paused_session",
    }
