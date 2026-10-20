"""
SentinelAI — REST API Routes

All endpoints are prefixed with /api by the app factory.

Endpoints:
    GET  /api/events          — recent events (query: limit, event_type, query)
    GET  /api/events/{id}     — single event by ID
    GET  /api/stats           — event counts by type
    GET  /api/health          — system health snapshot
    POST /api/llm/query       — direct local Hugging Face event QA
    GET  /api/event_types     — list of known event type strings
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from backend.database.event_database import EventDatabase
from backend.llm.assistant import LLMAssistant
from backend.retrival.retrival import EventRetriever

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Lazy-initialized singletons (shared with websocket module via module state)
# ---------------------------------------------------------------------------
# These are set by the main application on startup via set_shared_state().

_latest_jpeg: bytes | None = None
_preview_info = (None, 0)  # monotonic capture time and sequence; immutable snapshot
PREVIEW_STALE_S = 5.0

def update_preview(jpeg: bytes) -> None:
    global _latest_jpeg, _preview_info
    _latest_jpeg = jpeg
    _preview_info = (time.monotonic(), _preview_info[1] + 1)


def preview_status():
    captured_at, sequence = _preview_info
    age = max(0, time.monotonic() - captured_at) if captured_at is not None else None
    fresh = bool(_live_state.get("camera_ok") and _latest_jpeg and age is not None and age <= PREVIEW_STALE_S)
    return dict(frames_arriving=fresh, preview_sequence=sequence,
                preview_age_s=round(age, 3) if age is not None else None,
                preview_status="live" if fresh else "stale" if captured_at is not None else "waiting")


_db: EventDatabase | None = None
_retriever: EventRetriever | None = None
_llm: LLMAssistant | None = None
_ai = None
_system_start: float = time.time()

# Live state injected from the detection loop
_live_state: dict[str, Any] = {
    "camera_ok": False,
    "fps": 0.0,
    "track_count": 0,
    "active_event_types": [],
    "model_loaded": False,
    "vlm_adapter_loaded": False,
}


def set_shared_state(
    db: EventDatabase | None,
    retriever: EventRetriever | None,
    llm: LLMAssistant | None = None,
    ai=None,
) -> None:
    """Called by backend/main.py to inject live objects into the API."""
    global _db, _retriever, _llm, _ai
    _db = db
    _retriever = retriever
    _llm = llm
    _ai = ai


def update_live_state(**kwargs: Any) -> None:
    """Update live pipeline metrics pushed to the /api/health endpoint."""
    _live_state.update(kwargs)


def _get_db() -> EventDatabase:
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not initialized.")
    return _db


def _get_retriever() -> EventRetriever:
    if _retriever is None:
        raise HTTPException(status_code=503, detail="Retriever not initialized.")
    return _retriever


# ---------------------------------------------------------------------------
# Known event types
# ---------------------------------------------------------------------------

KNOWN_EVENT_TYPES = [
    "PERSON_ENTERED",
    "PERSON_EXITED",
    "ZONE_CHANGED",
    "LOITERING",
    "RUNNING",
    "UNATTENDED_OBJECT",
]


# ---------------------------------------------------------------------------
# Pydantic models for request/response
# ---------------------------------------------------------------------------

class LLMQueryRequest(BaseModel):
    question: str = Field(min_length=1,max_length=2000)
    event_type: str | None = None
    limit: int = Field(default=20,ge=1,le=20)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/events", summary="List recent events")
async def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    event_type: str | None = Query(default=None),
    query: str | None = Query(default=None, description="Full-text search"),
) -> JSONResponse:
    retriever = _get_retriever()

    if query:
        events = retriever.search(query, limit=limit)
    elif event_type:
        events = retriever.get_by_type(event_type, limit=limit)
    else:
        events = retriever.get_recent(limit=limit)

    return JSONResponse(content={"events": events, "count": len(events)})


@router.get("/events/{event_id}", summary="Get a single event by ID")
async def get_event(event_id: int) -> JSONResponse:
    retriever = _get_retriever()
    event = retriever.get_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")
    return JSONResponse(content=event)


@router.get("/stats", summary="Event counts by type")
async def get_stats() -> JSONResponse:
    retriever = _get_retriever()
    stats = retriever.get_stats()
    return JSONResponse(content=stats)


@router.get("/health", summary="System health")
async def get_health() -> JSONResponse:
    uptime = time.time() - _system_start
    data: dict[str, Any] = {
        "status": "ok",
        "uptime_s": round(uptime, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **_live_state,
    }
    if _db is not None:
        try:
            data["event_count"] = _db.count_events()
        except Exception:
            data["event_count"] = -1
    models = _ai.snapshot() if _ai is not None else {
        "vlm":{"state":"disabled","model_id":None,"error":None},
        "llm":_llm.snapshot() if _llm is not None else {"state":"disabled","model_id":None,"error":None}}
    data.update(models=models,vlm_status=models["vlm"]["state"],llm_status=models["llm"]["state"],
                vlm_loaded=models["vlm"]["state"]=="ready",
                vlm_adapter_loaded=models["vlm"].get("adapter_loaded",False),
                database_status="ready" if data.get("event_count",-1)>=0 else "error")
    data["yolo_status"]="ready" if data["model_loaded"] else "error" if data.get("pipeline_status")=="model_error" else "loading" if data.get("pipeline_status")=="starting" else "disabled"
    data.update(preview_status())
    pipeline = data.get("pipeline_status", "history_only")
    data["camera_status"] = ("ready" if data["frames_arriving"] else
        "degraded" if data["camera_ok"] else "error" if pipeline=="source_error" else
        "reconnecting" if pipeline=="reconnecting" else "starting" if pipeline=="starting" else "disconnected")
    if pipeline=="running" and not data["frames_arriving"]:
        data["fps"] = 0
    if data["database_status"]=="error" or pipeline in {"source_error","model_error","inference_error"}:
        data["status"]="error"
    elif any(m.get("enabled",False) and (m["state"]!="ready" or m.get("adapter_warning")) for m in models.values()) or (pipeline=="running" and not data["frames_arriving"]):
        data["status"]="degraded"
    data.setdefault("tracker_status","disabled")
    data.setdefault("event_engine_status","disabled")
    return JSONResponse(content=data)


@router.get("/event_types", summary="Known event type strings")
async def get_event_types() -> JSONResponse:
    return JSONResponse(content={"event_types": KNOWN_EVENT_TYPES})


@router.post("/llm/query", summary="Ask about retrieved events using a local Hugging Face model")
async def llm_query(body: LLMQueryRequest) -> JSONResponse:
    import asyncio
    from backend.llm.assistant import recorded_answer
    try:
        events, filters = _get_retriever().for_question(
            body.question,limit=body.limit,event_type=body.event_type)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    if _llm is None:
        return JSONResponse(content=dict(answer=recorded_answer(events),answer_kind="recorded_facts",
            source_event_ids=[x["id"] for x in events],sources=events,
            llm_status="disabled",llm_used=False,generation_status="disabled"))
    result = await asyncio.to_thread(_llm.query,body.question,events,filters)
    return JSONResponse(content=result)


@router.get("/models", summary="Local model lifecycle and errors")
async def model_status():
    return _ai.snapshot() if _ai else {"vlm":{"state":"disabled"},"llm":{"state":"disabled"}}


@router.post("/events/{event_id}/verify", summary="Queue the event's saved evidence for local Florence inference")
async def verify_event(event_id: int):
    from pathlib import Path
    from backend.config.settings import get_settings
    event = _get_retriever().get_by_id(event_id)
    if event is None:raise HTTPException(404,"Event not found")
    if _ai is None or not _ai.cfg.vlm.enabled:
        raise HTTPException(503,"VLM disabled; launch with --vlm")
    if not event.get("evidence_path"):raise HTTPException(422,"Event has no saved evidence")
    path=get_settings().resolve_path(event["evidence_path"])
    root=get_settings().resolve_path(get_settings().evidence.output_dir)
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(422,"Saved evidence is unavailable in the configured evidence directory")
    status=_ai.enqueue_event(event_id,event["event_type"],str(path),event["class_name"],event["zone"],force=True)
    if status in {"queue_full","error","stopped"}:raise HTTPException(503,status)
    return JSONResponse(status_code=202,content={"event_id":event_id,"verification_status":status})

@router.get("/frame.jpg", summary="Latest annotated host frame")
async def latest_frame():
    if not preview_status()["frames_arriving"]:
        raise HTTPException(404, "No live frame available")
    return Response(_latest_jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Preview-Sequence": str(_preview_info[1])})
