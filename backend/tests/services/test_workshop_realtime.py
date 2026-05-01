import asyncio
import uuid
from unittest.mock import AsyncMock

from app.services.workshop_realtime import (
    WorkshopRealtimeHub,
    WorkshopWsConnection,
)


def test_hub_publishes_participant_live_status_only_to_instructors() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        session_id = uuid.uuid4()

        trainee_socket = AsyncMock()
        trainee_socket.send_json = AsyncMock()
        instructor_a = AsyncMock()
        instructor_a.send_json = AsyncMock()
        instructor_b = AsyncMock()
        instructor_b.send_json = AsyncMock()

        user_trainee = uuid.uuid4()

        trainee = WorkshopWsConnection(
            websocket=trainee_socket,
            session_id=session_id,
            user_id=user_trainee,
            role="participant",
            part_generation=1,
        )
        inst1 = WorkshopWsConnection(
            websocket=instructor_a,
            session_id=session_id,
            user_id=uuid.uuid4(),
            role="instructor",
            part_generation=1,
        )
        inst2 = WorkshopWsConnection(
            websocket=instructor_b,
            session_id=session_id,
            user_id=uuid.uuid4(),
            role="instructor",
            part_generation=1,
        )

        await hub.attach(trainee)
        await hub.attach(inst1)
        await hub.attach(inst2)

        await hub.publish_participant_live_status(
            session_id=session_id,
            user_id=user_trainee,
            live_status="done",
        )

        trainee_socket.send_json.assert_not_awaited()
        instructor_a.send_json.assert_awaited_once()
        instructor_b.send_json.assert_awaited_once()
        call_kw = instructor_a.send_json.await_args.args[0]
        assert call_kw["type"] == "participant.live_status"
        assert call_kw["user_id"] == str(user_trainee)
        assert call_kw["live_status"] == "done"

        await hub.detach(trainee)
        await hub.detach(inst1)
        await hub.detach(inst2)

    asyncio.run(runner())


def test_hub_sync_bump_room_aligns_connection_part_generation() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        session_id = uuid.uuid4()

        a = WorkshopWsConnection(
            websocket=AsyncMock(),
            session_id=session_id,
            user_id=uuid.uuid4(),
            role="participant",
            part_generation=1,
        )
        b = WorkshopWsConnection(
            websocket=AsyncMock(),
            session_id=session_id,
            user_id=uuid.uuid4(),
            role="instructor",
            part_generation=1,
        )
        await hub.attach(a)
        await hub.attach(b)

        hub.sync_bump_room_part_generation(session_id, 9)

        assert a.part_generation == 9
        assert b.part_generation == 9

        await hub.detach(a)
        await hub.detach(b)

    asyncio.run(runner())


def test_hub_status_changed_reaches_participants_and_instructors() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        session_id = uuid.uuid4()

        trainee_socket = AsyncMock()
        trainee_socket.send_json = AsyncMock()
        instructor_socket = AsyncMock()
        instructor_socket.send_json = AsyncMock()

        trainee = WorkshopWsConnection(
            websocket=trainee_socket,
            session_id=session_id,
            user_id=uuid.uuid4(),
            role="participant",
            part_generation=1,
        )
        instructor = WorkshopWsConnection(
            websocket=instructor_socket,
            session_id=session_id,
            user_id=uuid.uuid4(),
            role="instructor",
            part_generation=1,
        )

        await hub.attach(trainee)
        await hub.attach(instructor)

        await hub.publish_session_status_changed(
            session_id=session_id,
            status="paused",
        )

        for sock in (trainee_socket, instructor_socket):
            sock.send_json.assert_awaited_once()
            payload = sock.send_json.await_args.args[0]
            assert payload["type"] == "session.status_changed"
            assert payload["status"] == "paused"
            assert payload["session_id"] == str(session_id)

        await hub.detach(trainee)
        await hub.detach(instructor)

    asyncio.run(runner())
