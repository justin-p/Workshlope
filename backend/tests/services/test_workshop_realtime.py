import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

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


def test_hub_detach_is_idempotent_when_room_already_empty() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        sid = uuid.uuid4()
        c = WorkshopWsConnection(
            websocket=AsyncMock(),
            session_id=sid,
            user_id=uuid.uuid4(),
            role="participant",
            part_generation=1,
        )
        await hub.attach(c)
        await hub.detach(c)
        await hub.detach(c)

    asyncio.run(runner())


def test_hub_sync_bump_no_connections_is_noop() -> None:
    hub = WorkshopRealtimeHub()
    hub.sync_bump_room_part_generation(uuid.uuid4(), 3)


def test_hub_publish_fanout_swallows_send_json_errors_on_participant_status() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        sid = uuid.uuid4()

        bad_instructor_ws = AsyncMock()
        bad_instructor_ws.send_json = AsyncMock(
            side_effect=RuntimeError("socket closed"),
        )

        trainee = WorkshopWsConnection(
            websocket=AsyncMock(),
            session_id=sid,
            user_id=uuid.uuid4(),
            role="participant",
            part_generation=1,
        )
        flaky = WorkshopWsConnection(
            websocket=bad_instructor_ws,
            session_id=sid,
            user_id=uuid.uuid4(),
            role="instructor",
            part_generation=1,
        )

        await hub.attach(trainee)
        await hub.attach(flaky)

        await hub.publish_participant_live_status(
            session_id=sid,
            user_id=trainee.user_id,
            live_status="done",
        )

        await hub.detach(trainee)
        await hub.detach(flaky)

    asyncio.run(runner())


def test_hub_publish_session_part_changed_swallows_send_errors() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        sid = uuid.uuid4()

        bad = AsyncMock()
        bad.send_json = AsyncMock(side_effect=BrokenPipeError())

        flaky = WorkshopWsConnection(
            websocket=bad,
            session_id=sid,
            user_id=uuid.uuid4(),
            role="instructor",
            part_generation=1,
        )

        await hub.attach(flaky)

        await hub.publish_session_part_changed(
            session_id=sid,
            part_index=0,
            part_slug="a",
            part_generation=2,
        )

        await hub.detach(flaky)

    asyncio.run(runner())


def test_hub_publish_session_status_changed_swallows_send_errors() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        sid = uuid.uuid4()

        bad = AsyncMock()
        bad.send_json = AsyncMock(side_effect=OSError("boom"))

        flaky = WorkshopWsConnection(
            websocket=bad,
            session_id=sid,
            user_id=uuid.uuid4(),
            role="participant",
            part_generation=1,
        )

        await hub.attach(flaky)

        await hub.publish_session_status_changed(session_id=sid, status="ended")

        await hub.detach(flaky)

    asyncio.run(runner())


def test_hub_timer_operations_cover_state_branches() -> None:
    async def runner() -> None:
        hub = WorkshopRealtimeHub()
        sid = uuid.uuid4()

        with pytest.raises(ValueError, match="timer_not_active"):
            await hub.pause_timer(session_id=sid)

        with pytest.raises(ValueError, match="timer_not_active"):
            await hub.resume_timer(session_id=sid)

        started = await hub.start_timer(
            session_id=sid,
            mode="countdown",
            target_seconds=30,
        )
        assert started.status == "running"

        with pytest.raises(ValueError, match="timer_already_active"):
            await hub.start_timer(
                session_id=sid,
                mode="countup",
                target_seconds=None,
            )

        paused = await hub.pause_timer(session_id=sid)
        assert paused.status == "paused"
        assert paused.paused_at is not None

        with pytest.raises(ValueError, match="timer_not_running"):
            await hub.pause_timer(session_id=sid)

        resumed = await hub.resume_timer(session_id=sid)
        assert resumed.status == "running"

        with pytest.raises(ValueError, match="timer_not_paused"):
            await hub.resume_timer(session_id=sid)

        assert await hub.get_timer(session_id=sid) is not None

        await hub.stop_timer(session_id=sid)

        with pytest.raises(ValueError, match="timer_not_active"):
            await hub.stop_timer(session_id=sid)

        assert await hub.get_timer(session_id=sid) is None

    asyncio.run(runner())
