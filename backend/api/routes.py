
"""REST API for the dashboard and external clients."""

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from backend.config.settings import Settings
from backend.database.event_database import EventDatabase
from backend.llm.assistant import Assistant
from backend.retrieval.retriever import EventRetriever

LIVE_DIR = Path("data/live")
LIVE_STALE_SEC = 5.0


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


def _row_to_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api")

    def open_db() -> EventDatabase:
        return EventDatabase(settings.database_path)

    def make_assistant(database: EventDatabase) -> Assistant:
        return Assistant(
            EventRetriever(database),
            gemini_api_keys=settings.gemini_api_keys,
            gemini_api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout=settings.llm_timeout_sec,
        )

    # Health and status

    @router.get("/health")
    def health():
        return {"status": "ok"}

    @router.get("/status")
    def status():
        database = open_db()

        try:
            total = database.count_events()
            by_type = database.count_by_type()
            assistant = make_assistant(database)
            llm_available = assistant.llm_available()
        finally:
            database.close()

        live = _read_live_status()

        return {
            "total_events": total,
            "events_by_type": by_type,
            "pipeline_online": live["online"],
            "live": live,
            # Indicates configured keys, not verified API connectivity.
            "llm_available": llm_available,
            "llm_configured": llm_available,
            "llm_provider": "Gemini API",
            "llm_model": settings.gemini_model,
            "gemini_keys_configured": len(
                set(settings.gemini_api_keys)
                | ({settings.gemini_api_key} if settings.gemini_api_key else set())
            ),
            "esp32_configured": bool(settings.esp32_url),
            "vlm_enabled": settings.vlm_enabled,
            "vlm_adapter": bool(settings.vlm_adapter_path),
        }

    # Event list and event details

    @router.get("/events")
    def list_events(
        event_type: str | None = Query(None, alias="type"),
        zone: str | None = None,
        since_minutes: int | None = Query(
            None, ge=1, le=60 * 24 * 365
        ),
        limit: int = Query(50, ge=1, le=500),
    ):
        since = (
            datetime.now() - timedelta(minutes=since_minutes)
            if since_minutes
            else None
        )

        database = open_db()

        try:
            rows = database.query_events(
                event_type=event_type,
                zone=zone,
                since=since,
                limit=limit,
            )
            return [_row_to_dict(row) for row in rows]
        finally:
            database.close()

    @router.get("/events/{event_id}")
    def get_event(event_id: int):
        database = open_db()

        try:
            row = database.get_event(event_id)
        finally:
            database.close()

        if row is None:
            raise HTTPException(404, "Event not found")

        return _row_to_dict(row)

    @router.get("/evidence/{event_id}")
    def get_evidence(event_id: int):
        database = open_db()

        try:
            row = database.get_event(event_id)
        finally:
            database.close()

        if row is None or not row["evidence_path"]:
            raise HTTPException(404, "No evidence for this event")

        path = Path(row["evidence_path"]).resolve()
        evidence_root = Path(settings.evidence_dir).resolve()

        # Prevent serving files outside the evidence directory.
        if not path.is_relative_to(evidence_root) or not path.is_file():
            raise HTTPException(404, "Evidence file not available")

        return FileResponse(path, media_type="image/jpeg")

    # Gemini natural-language assistant

    @router.post("/ask")
    def ask(body: AskRequest):
        database = open_db()

        try:
            assistant = make_assistant(database)
            return assistant.ask(body.question)
        finally:
            database.close()

    # Live camera feed

    @router.get("/live.jpg")
    def live_frame():
        frame_path = LIVE_DIR / "latest.jpg"

        if not frame_path.is_file():
            raise HTTPException(404, "No live frame yet")

        return Response(
            frame_path.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/stream")
    async def stream(request: Request):
        frame_path = LIVE_DIR / "latest.jpg"

        async def generate():
            last_mtime = 0.0

            while True:
                if await request.is_disconnected():
                    break

                try:
                    mtime = frame_path.stat().st_mtime

                    if mtime != last_mtime:
                        last_mtime = mtime
                        data = frame_path.read_bytes()

                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(data)}\r\n\r\n".encode()
                            + data
                            + b"\r\n"
                        )
                except OSError:
                    pass

                await asyncio.sleep(0.15)

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return router


def _read_live_status() -> dict:
    status_path = LIVE_DIR / "status.json"

    try:
        data = json.loads(status_path.read_text())
    except (OSError, ValueError):
        return {"online": False}

    age = time.time() - data.get("updated_at", 0)
    data["online"] = age < LIVE_STALE_SEC

    return data
