"""
SentinelAI — WebSocket live stream

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

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket client connected. Total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        logger.info("WebSocket client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON payload to all connected clients. Dead connections are pruned."""
        if not self._connections:
            return
        text = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._connections:
                self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Module-level manager — shared by the routes and the detection loop
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


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _event_loop
    _event_loop = loop


def _schedule_broadcast(payload: dict[str, Any]) -> None:
    if _event_loop is None:
        return  # API not running yet
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(payload), _event_loop)
    except Exception as exc:
        logger.debug("WebSocket broadcast error: %s", exc)
