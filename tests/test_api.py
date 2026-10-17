
"""API tests. Skipped automatically when fastapi/httpx are not installed
(pip install -r requirements.txt)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient

    from backend.api import routes
    from backend.api.app import create_app

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

from backend.config.settings import Settings
from backend.database.event_database import EventDatabase
from tests.helpers import add_event


@unittest.skipUnless(HAVE_FASTAPI, "fastapi / httpx not installed")
class ApiTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        root = Path(self.tmp.name)

        self.evidence_dir = root / "events"
        self.evidence_dir.mkdir()

        self.db_path = str(root / "e.db")

        self.live_dir = root / "live"
        self.live_dir.mkdir()

        patcher = mock.patch.object(routes, "LIVE_DIR", self.live_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Explicitly disable Gemini for ordinary API tests.
        # These settings must not depend on the developer's .env file.
        settings = Settings(
            database_path=self.db_path,
            evidence_dir=str(self.evidence_dir),
            ollama_url="http://127.0.0.1:1",
            esp32_url="",
            gemini_api_key="",
            gemini_api_keys=[],
        )

        self.client = TestClient(create_app(settings))

        database = EventDatabase(self.db_path)

        good_jpg = self.evidence_dir / "ok.jpg"
        good_jpg.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

        secret = root / "secret.txt"
        secret.write_text("do not serve", encoding="utf-8")

        self.unattended = add_event(
            database,
            "UNATTENDED_OBJECT",
            minutes_ago=0,
            evidence_path=str(good_jpg),
        )

        self.loitering = add_event(
            database,
            "LOITERING",
            class_name="person",
            minutes_ago=0,
            zone="lobby",
            evidence_path=str(secret),
        )

        self.no_evidence = add_event(
            database,
            "RUNNING",
            class_name="person",
            minutes_ago=0,
        )

        database.close()

    def test_health_and_dashboard(self):
        self.assertEqual(
            self.client.get("/api/health").json(),
            {"status": "ok"},
        )

        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("SentinelAI", page.text)

    def test_list_and_filter_events(self):
        everything = self.client.get("/api/events").json()
        self.assertEqual(len(everything), 3)
        self.assertEqual(everything[0]["id"], self.no_evidence)

        only = self.client.get(
            "/api/events",
            params={"type": "LOITERING"},
        ).json()
        self.assertEqual([e["id"] for e in only], [self.loitering])

        by_zone = self.client.get(
            "/api/events",
            params={"zone": "lobby"},
        ).json()
        self.assertEqual([e["id"] for e in by_zone], [self.loitering])

        self.assertEqual(
            self.client.get(
                "/api/events",
                params={"limit": 0},
            ).status_code,
            422,
        )

    def test_get_event(self):
        response = self.client.get(f"/api/events/{self.unattended}")
        event = response.json()

        self.assertEqual(event["event_type"], "UNATTENDED_OBJECT")
        self.assertIn("verification", event)

        self.assertEqual(
            self.client.get("/api/events/9999").status_code,
            404,
        )

    def test_evidence_served_only_from_evidence_dir(self):
        ok = self.client.get(f"/api/evidence/{self.unattended}")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.headers["content-type"], "image/jpeg")

        # Evidence outside the permitted directory must not be served.
        self.assertEqual(
            self.client.get(f"/api/evidence/{self.loitering}").status_code,
            404,
        )

        # Events without evidence must return 404.
        self.assertEqual(
            self.client.get(f"/api/evidence/{self.no_evidence}").status_code,
            404,
        )

    def test_ask_falls_back_without_llm(self):
        response = self.client.post(
            "/api/ask",
            json={"question": "was there an unattended object?"},
        )
        body = response.json()

        self.assertFalse(body["llm_used"])
        self.assertEqual(
            [e["id"] for e in body["events"]],
            [self.unattended],
        )
        self.assertIn(
            f"[event {self.unattended}]",
            body["answer"],
        )

    def test_ask_validates_input(self):
        self.assertEqual(
            self.client.post(
                "/api/ask",
                json={"question": ""},
            ).status_code,
            422,
        )

        self.assertEqual(
            self.client.post("/api/ask", json={}).status_code,
            422,
        )

        self.assertEqual(
            self.client.post(
                "/api/ask",
                json={"question": "x" * 501},
            ).status_code,
            422,
        )

    def test_status_pipeline_offline_then_online(self):
        status = self.client.get("/api/status").json()

        self.assertEqual(status["total_events"], 3)
        self.assertFalse(status["pipeline_online"])
        self.assertFalse(status["llm_available"])
        self.assertFalse(status["esp32_configured"])

        (self.live_dir / "status.json").write_text(
            '{"fps": 9.5, "tracks": 2, "updated_at": %f}'
            % __import__("time").time(),
            encoding="utf-8",
        )

        status = self.client.get("/api/status").json()

        self.assertTrue(status["pipeline_online"])
        self.assertEqual(status["live"]["tracks"], 2)

    def test_live_frame(self):
        self.assertEqual(
            self.client.get("/api/live.jpg").status_code,
            404,
        )

        (self.live_dir / "latest.jpg").write_bytes(b"\xff\xd8frame")

        response = self.client.get("/api/live.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\xff\xd8frame")


if __name__ == "__main__":
    unittest.main()
