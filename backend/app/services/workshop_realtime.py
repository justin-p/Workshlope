from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import WebSocket


@dataclass(slots=True)
class WorkshopWsConnection:
    websocket: WebSocket
    session_id: uuid.UUID
    user_id: uuid.UUID
    role: Literal["participant", "instructor"]
    #: Mutated in-process when instructors advance parts (see sync_bump_room_part_generation).
    part_generation: int


class WorkshopRealtimeHub:
    """In-memory workshop session fan-out (single-process MVP).

    Trainee connections must never receive roster-style events (identity + live status)
    emitted by other trainees; instructors receive those updates.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rooms: dict[uuid.UUID, list[WorkshopWsConnection]] = {}

    async def attach(self, connection: WorkshopWsConnection) -> None:
        async with self._lock:
            self._rooms.setdefault(connection.session_id, []).append(connection)

    async def detach(self, connection: WorkshopWsConnection) -> None:
        async with self._lock:
            room = self._rooms.get(connection.session_id)
            if not room:
                return
            self._rooms[connection.session_id] = [
                conn for conn in room if conn is not connection
            ]

    async def publish_participant_live_status(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        live_status: str,
    ) -> None:
        payload = {
            "type": "participant.live_status",
            "session_id": str(session_id),
            "user_id": str(user_id),
            "live_status": live_status,
        }
        async with self._lock:
            room = list(self._rooms.get(session_id, []))
        for conn in room:
            if conn.role != "instructor":
                continue
            try:
                await conn.websocket.send_json(payload)
            except Exception:
                # Best-effort fan-out; stale sockets are skipped.
                continue

    def sync_bump_room_part_generation(
        self, session_id: uuid.UUID, part_generation: int
    ) -> None:
        """Align in-memory connection tokens with DB after ``part.advance`` commits.

        Call synchronously immediately after committing the WorkshopSession generation
        bump (same task, before any ``await``) so other coroutines cannot observe DB
        ahead of mirrored connection state in the single-worker MVP.
        """
        room = self._rooms.get(session_id)
        if not room:
            return
        for conn in list(room):
            conn.part_generation = part_generation

    async def publish_session_part_changed(
        self,
        *,
        session_id: uuid.UUID,
        part_index: int,
        part_slug: str,
        part_generation: int,
    ) -> None:
        payload = {
            "type": "session.part_changed",
            "session_id": str(session_id),
            "part_index": part_index,
            "part_slug": part_slug,
            "part_generation": part_generation,
        }
        async with self._lock:
            room = list(self._rooms.get(session_id, []))
        for conn in room:
            try:
                await conn.websocket.send_json(payload)
            except Exception:
                continue

    async def publish_session_status_changed(
        self,
        *,
        session_id: uuid.UUID,
        status: str,
    ) -> None:
        payload = {
            "type": "session.status_changed",
            "session_id": str(session_id),
            "status": status,
        }
        async with self._lock:
            room = list(self._rooms.get(session_id, []))
        for conn in room:
            try:
                await conn.websocket.send_json(payload)
            except Exception:
                continue


workshop_hub = WorkshopRealtimeHub()
