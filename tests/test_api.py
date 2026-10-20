# tests/test_api.py
"""
Tests for the FastAPI application â€” no camera, no model loading.
Uses TestClient to verify routes without a running server.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Set up the app with a temp database before starting the test client."""
    from backend.config.settings import reset_settings
    reset_settings()

    # Create a temp DB and inject it into API state
    from backend.database.event_database import EventDatabase
    from backend.retrival.retrival import EventRetriever
    from backend.api import routes as api_routes

    db_path = str(tmp_path_factory.mktemp("db") / "test.db")
    db = EventDatabase(database_path=db_path)
    retriever = EventRetriever(db)
    api_routes.set_shared_state(db=db, retriever=retriever, llm=None)

    # Seed one event
    from datetime import datetime
    from backend.schemas.event import Event
    ev = Event("LOITERING", 1, "person", datetime.now(), zone="entrance",
               description="test loitering event")
    db.save_event(ev, evidence_path="data/events/test.jpg")

    from backend.api import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    db.close()
    reset_settings()


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "uptime_s" in data


def test_events_endpoint_returns_list(client):
    r = client.get("/api/events?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert isinstance(data["events"], list)
    assert data["count"] >= 1


def test_events_endpoint_by_type(client):
    r = client.get("/api/events?event_type=LOITERING")
    assert r.status_code == 200
    data = r.json()
    assert all(e["event_type"] == "LOITERING" for e in data["events"])


def test_events_search(client):
    r = client.get("/api/events?query=loitering")
    assert r.status_code == 200
    data = r.json()
    assert len(data["events"]) >= 1


def test_event_by_id(client):
    r = client.get("/api/events/1")
    assert r.status_code == 200
    ev = r.json()
    assert ev["id"] == 1
    assert ev["event_type"] == "LOITERING"


def test_event_not_found(client):
    r = client.get("/api/events/99999")
    assert r.status_code == 404


def test_stats_endpoint(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "by_type" in data
    assert data["total"] >= 1


def test_event_types_endpoint(client):
    r = client.get("/api/event_types")
    assert r.status_code == 200
    data = r.json()
    assert "LOITERING" in data["event_types"]
    assert "RUNNING" in data["event_types"]


def test_llm_query_without_llm(client):
    """LLM endpoint should return gracefully when LLM is None."""
    r = client.post("/api/llm/query", json={"question": "What happened?"})
    assert r.status_code == 200
    data = r.json()
    assert "answer" in data



def test_websocket_disconnect_after_failed_broadcast_is_idempotent():
    import asyncio
    from backend.api.websocket import ConnectionManager
    class ClosedSocket:
        async def accept(self):pass
        async def send_text(self,text):raise RuntimeError("peer closed")
    async def exercise():
        manager=ConnectionManager();socket=ClosedSocket()
        await manager.connect(socket)
        await manager.broadcast(dict(type="frame"))
        assert manager.connection_count==0
        # Endpoint finally/exception cleanup can follow broadcast pruning.
        manager.disconnect(socket)
        manager.disconnect(socket)
        assert manager.connection_count==0
    asyncio.run(exercise())
