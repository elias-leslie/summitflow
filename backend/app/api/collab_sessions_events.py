from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket


class CollabEventHub:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._sequences: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str) -> int:
        await websocket.accept()
        async with self._lock:
            self._connections[session_id].append(websocket)
            return self._sequences[session_id]

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        async with self._lock:
            if websocket in self._connections[session_id]:
                self._connections[session_id].remove(websocket)
            if not self._connections[session_id]:
                self._connections.pop(session_id, None)

    async def current_sequence(self, session_id: str) -> int:
        async with self._lock:
            return self._sequences[session_id]

    async def broadcast(
        self,
        session_id: str,
        action: str,
        data: dict[str, Any],
    ) -> None:
        async with self._lock:
            self._sequences[session_id] += 1
            sequence = self._sequences[session_id]
            connections = list(self._connections.get(session_id, []))
        if not connections:
            return
        payload = {
            "type": "collab_event",
            "session_id": session_id,
            "sequence": sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "data": data,
        }
        disconnected: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            await self.disconnect(websocket, session_id)
