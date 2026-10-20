"""
SentinelAI — FastAPI application factory

Creates and configures the FastAPI app, mounts static files for the
dashboard, and includes all routers.

Usage:
    uvicorn backend.api:app --host 0.0.0.0 --port 8000

Or via main entry point:
    python -m backend.main
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router as api_router
from backend.api.websocket import router as ws_router

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    import asyncio
    from backend.config.settings import get_settings
    from backend.database.event_database import EventDatabase
    from backend.retrival.retrival import EventRetriever
    from backend.api import routes
    from backend.api.websocket import set_event_loop
    set_event_loop(asyncio.get_running_loop())
    owned_db = None
    owned_ai = None
    if routes._db is None:
        cfg = get_settings()
        owned_db = EventDatabase(str(cfg.resolve_path(cfg.database.path)))
        from backend.ai_runtime.manager import AIManager
        owned_ai = AIManager(cfg,owned_db)
        owned_ai.start()
        routes.set_shared_state(owned_db, EventRetriever(owned_db),owned_ai.llm,ai=owned_ai)
    try:
        yield
    finally:
        set_event_loop(None)
        if owned_ai is not None:
            owned_ai.stop()
        if owned_db is not None:
            routes.set_shared_state(None, None)
            owned_db.close()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="SentinelAI",
        description=(
            "Autonomous edge intelligence — YOLO11n + ByteTrack + "
            "deterministic event reasoning + optional Florence-2 visual verification."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    # Serve evidence keyframe images
    from backend.config.settings import get_settings
    cfg = get_settings()
    evidence_dir = cfg.resolve_path(cfg.evidence.output_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/evidence",
        StaticFiles(directory=str(evidence_dir)),
        name="evidence",
    )

    # Serve the dashboard
    dashboard_dir = cfg.resolve_path("dashboard")
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/",
        StaticFiles(directory=str(dashboard_dir), html=True),
        name="dashboard",
    )

    return app


# Module-level instance — picked up by uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
