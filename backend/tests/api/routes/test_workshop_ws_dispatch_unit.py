"""Inner ``Session()`` failure branches in websocket message dispatch."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes import workshop_sessions as ws_mod
from app.services.workshop_realtime import WorkshopWsConnection


def _cm(mock_db: MagicMock) -> MagicMock:
    out = MagicMock()
    out.__enter__ = MagicMock(return_value=mock_db)
    out.__exit__ = MagicMock(return_value=None)
    return out


def test_dispatch_live_status_inner_missing_session_returns_error() -> None:
    async def _run() -> None:
        snap_db = MagicMock()
        alive = MagicMock()
        alive.part_generation = 1
        snap_db.get.return_value = alive

        inner_db = MagicMock()
        inner_db.get.return_value = None

        order = [_cm(snap_db), _cm(inner_db)]

        def fake_session(*_a: object, **_kw: object) -> MagicMock:
            return order.pop(0)

        sid = uuid.uuid4()
        uid = uuid.uuid4()
        websocket = AsyncMock()
        handshake = ws_mod.WorkshopWsHandshake(
            user_id=uid, role="participant", part_generation=1
        )
        conn = WorkshopWsConnection(
            websocket=websocket,  # type: ignore[arg-type]
            session_id=sid,
            user_id=uid,
            role="participant",
            part_generation=1,
        )
        text = json.dumps({"type": "live_status", "live_status": "done"})

        with patch.object(ws_mod, "Session", side_effect=fake_session):
            ret = await ws_mod._dispatch_workshop_ws_text(
                websocket=websocket,
                session_id=sid,
                handshake=handshake,
                connection=conn,
                text=text,
            )
        assert ret is True
        websocket.send_json.assert_any_await(
            {"type": "error", "detail": "session_not_found"}
        )

    asyncio.run(_run())


def test_dispatch_session_pause_inner_missing_session_returns_error() -> None:
    async def _run() -> None:
        snap_db = MagicMock()
        alive = MagicMock()
        alive.part_generation = 1
        snap_db.get.return_value = alive

        inner_db = MagicMock()
        inner_db.get.return_value = None

        order = [_cm(snap_db), _cm(inner_db)]

        def fake_session(*_a: object, **_kw: object) -> MagicMock:
            return order.pop(0)

        sid = uuid.uuid4()
        uid = uuid.uuid4()
        websocket = AsyncMock()
        handshake = ws_mod.WorkshopWsHandshake(
            user_id=uid, role="instructor", part_generation=1
        )
        conn = WorkshopWsConnection(
            websocket=websocket,  # type: ignore[arg-type]
            session_id=sid,
            user_id=uid,
            role="instructor",
            part_generation=1,
        )
        text = json.dumps({"type": "session.pause"})

        with patch.object(ws_mod, "Session", side_effect=fake_session):
            ret = await ws_mod._dispatch_workshop_ws_text(
                websocket=websocket,
                session_id=sid,
                handshake=handshake,
                connection=conn,
                text=text,
            )
        assert ret is True
        websocket.send_json.assert_any_await(
            {"type": "error", "detail": "session_not_found"}
        )

    asyncio.run(_run())


def test_dispatch_session_resume_inner_missing_session_returns_error() -> None:
    async def _run() -> None:
        snap_db = MagicMock()
        alive = MagicMock()
        alive.part_generation = 1
        snap_db.get.return_value = alive

        inner_db = MagicMock()
        inner_db.get.return_value = None

        order = [_cm(snap_db), _cm(inner_db)]

        def fake_session(*_a: object, **_kw: object) -> MagicMock:
            return order.pop(0)

        sid = uuid.uuid4()
        uid = uuid.uuid4()
        websocket = AsyncMock()
        handshake = ws_mod.WorkshopWsHandshake(
            user_id=uid, role="instructor", part_generation=1
        )
        conn = WorkshopWsConnection(
            websocket=websocket,  # type: ignore[arg-type]
            session_id=sid,
            user_id=uid,
            role="instructor",
            part_generation=1,
        )
        text = json.dumps({"type": "session.resume"})

        with patch.object(ws_mod, "Session", side_effect=fake_session):
            ret = await ws_mod._dispatch_workshop_ws_text(
                websocket=websocket,
                session_id=sid,
                handshake=handshake,
                connection=conn,
                text=text,
            )
        assert ret is True
        websocket.send_json.assert_any_await(
            {"type": "error", "detail": "session_not_found"}
        )

    asyncio.run(_run())
