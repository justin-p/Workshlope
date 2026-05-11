"""Per-user WebSocket fan-out for workshop dashboard list invalidation (single-process MVP)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable

from fastapi import WebSocket


class UserWorkshopFeedHub:
    """In-memory connections keyed by user_id (same worker as workshop hub)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_user: dict[uuid.UUID, list[WebSocket]] = {}

    async def attach(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            self._by_user.setdefault(user_id, []).append(websocket)

    async def detach(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._by_user.get(user_id)
            if not conns:
                return
            remaining = [c for c in conns if c is not websocket]
            if remaining:
                self._by_user[user_id] = remaining
            else:
                del self._by_user[user_id]

    async def notify_workshop_sessions_list_changed(
        self,
        user_ids: Iterable[uuid.UUID],
        *,
        session_id: uuid.UUID,
    ) -> None:
        payload = {
            "type": "workshop_sessions_list_changed",
            "reason": "roster",
            "session_id": str(session_id),
        }
        unique = list(dict.fromkeys(user_ids))
        async with self._lock:
            targets: list[tuple[uuid.UUID, list[WebSocket]]] = [
                (uid, list(self._by_user.get(uid, []))) for uid in unique
            ]
        for _uid, conns in targets:
            for ws in conns:
                try:
                    await ws.send_json(payload)
                except Exception:
                    continue


user_workshop_feed_hub = UserWorkshopFeedHub()
