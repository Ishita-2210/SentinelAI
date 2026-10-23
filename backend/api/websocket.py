"""
SentinelAI - WebSocket live stream

Endpoint: ws://localhost:8000/ws/stream

The detection loop pushes JSON frames to all connected clients every
time a frame is processed. Clients receive:
  {
    "type": "frame",
    "timestamp": "2026-10-19T14:23:00.000Z",
    "tracks": [{"track_id": 1, "class_name": "person", "box": [x1,y1,x2,y2], "zone": "entrance"}],
    "events":  [{"event_type": "LOITERING", "track_id": 1, "zone": "entrance", "description": "..."}],
    "fps": 28.3
  }

Clients can also receive {type: "event"} messages for database events
with VLM results when they become available.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Tracks all active WebSocket connections and broadcasts to them."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self.send_timeout_s = 1.0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket client connected. Total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws not in self._connections:
            return  # A failed broadcast may already have removed this socket.
        self._connections.remove(ws)
        logger.info("WebSocket client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON payload to all connected clients. Dead connections are pruned."""
        if not self._connections:
            return
        text = json.dumps(data, default=str)
        async def send(ws):
            try:
                await asyncio.wait_for(ws.send_text(text), self.send_timeout_s)
            except Exception:
                self.disconnect(ws)
                try:
                    await asyncio.wait_for(ws.close(code=1013), self.send_timeout_s)
                except Exception:
                    pass
        await asyncio.gather(*(send(ws) for ws in tuple(self._connections)))

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Module-level manager - shared by the routes and the detection loop
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/stream")
async def websocket_stream(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; the server pushes data via broadcast()
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Helper called from the detection loop (synchronous thread)
# ---------------------------------------------------------------------------

def push_frame(
    tracks: list[dict[str, Any]],
    events: list[dict[str, Any]],
    fps: float,
    timestamp: str,
) -> None:
    """
    Push a detection frame update to all WebSocket clients.

    This function is called from the synchronous detection loop thread.
    It schedules the async broadcast on the event loop running in the
    API server thread.
    """
    payload = {
        "type": "frame",
        "timestamp": timestamp,
        "tracks": tracks,
        "events": events,
        "fps": round(fps, 1),
    }
    _schedule_broadcast(payload)


def push_event_result(event_id: int, event_data: dict[str, Any]) -> None:
    """Push a VLM result update to all WebSocket clients."""
    payload = {
        "type": "vlm_result",
        "event_id": event_id,
        **event_data,
    }
    _schedule_broadcast(payload)


# Lazily-set event loop reference (set by main.py when starting the API thread)
_event_loop: asyncio.AbstractEventLoop | None = None
_broadcast_lock = threading.Lock()
_latest_frame: dict[str, Any] | None = None
_event_updates: deque = deque(maxlen=64)
_drain_scheduled = False


def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _event_loop, _latest_frame, _drain_scheduled
    with _broadcast_lock:
        _event_loop = loop
        _latest_frame = None
        _event_updates.clear()
        _drain_scheduled = False


async def _drain_broadcasts() -> None:
    """One task drains a latest-frame slot and bounded event notifications.

    SQLite/REST remains authoritative if an older notification is displaced.
    """
    global _latest_frame, _drain_scheduled
    try:
        while True:
            with _broadcast_lock:
                if _event_updates:
                    payload = _event_updates.popleft()
                elif _latest_frame is not None:
                    payload, _latest_frame = _latest_frame, None
                else:
                    _drain_scheduled = False
                    return
            await manager.broadcast(payload)
    except BaseException:
        with _broadcast_lock:
            _drain_scheduled = False
        raise


def _schedule_broadcast(payload: dict[str, Any]) -> None:
    global _latest_frame, _drain_scheduled
    with _broadcast_lock:
        if _event_loop is None or _event_loop.is_closed():
            return
        if payload.get("type") == "frame":
            _latest_frame = payload
        else:
            _event_updates.append(payload)
        if _drain_scheduled:
            return
        _drain_scheduled = True
        coroutine = _drain_broadcasts()
        try:
            asyncio.run_coroutine_threadsafe(coroutine, _event_loop)
        except Exception as exc:
            coroutine.close()
            _drain_scheduled = False
            logger.debug("WebSocket broadcast error: %s", exc)
