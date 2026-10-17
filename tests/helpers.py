"""Shared test helpers."""

import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from backend.database.event_database import EventDatabase
from backend.schemas.event import Event

NOW = datetime(2026, 10, 17, 12, 0, 0)


def add_event(
    database: EventDatabase,
    event_type: str = "UNATTENDED_OBJECT",
    class_name: str = "backpack",
    minutes_ago: float = 5,
    zone: str | None = "entrance",
    description: str = "",
    track_id: int = 1,
    evidence_path: str | None = None,
) -> int:

    event = Event(
        event_type=event_type,
        track_id=track_id,
        class_name=class_name,
        timestamp=NOW - timedelta(minutes=minutes_ago),
        zone=zone,
        confidence=0.9,
        description=description or f"{class_name} {event_type.lower()}",
    )

    return database.save_event(event, evidence_path)


class FakeServer:
    """Tiny local HTTP server that records requests and replies with a
    fixed JSON body. Used to stand in for Ollama and the ESP32."""

    def __init__(self, reply: dict | None = None, status: int = 200):
        self.requests: list[dict] = []
        outer = self
        body = json.dumps(reply or {}).encode()

        class Handler(BaseHTTPRequestHandler):

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                payload = self.rfile.read(length).decode() if length else ""

                outer.requests.append(
                    {"method": self.command, "path": self.path, "body": payload}
                )

                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _handle
            do_POST = _handle

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
