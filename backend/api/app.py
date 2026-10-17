"""SentinelAI API + dashboard server.

Run:
    python -m backend.api.app
Then open http://127.0.0.1:8000
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from backend.api.routes import build_router
from backend.config.settings import Settings, get_settings

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:

    settings = settings or get_settings()

    app = FastAPI(
        title="SentinelAI",
        description="Event-driven edge intelligence for real-time scene understanding",
    )

    app.include_router(build_router(settings))

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def main():
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "backend.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
    )


if __name__ == "__main__":
    main()
