"""
SentinelAI — Event Database (SQLite)

Stores all detected events with evidence paths and VLM verification results.
Safe for concurrent reads from the API thread and writes from the detection loop.

Schema migration is additive: new columns are added with ALTER TABLE if the
database already exists from a previous version. No data is ever dropped.
"""
from __future__ import annotations

import logging
import json
import sqlite3
import threading
from functools import wraps
from pathlib import Path

from backend.schemas.event import Event

logger = logging.getLogger(__name__)


def serialized_read(method):
    """One SQLite connection: reads must not join another thread's transaction."""
    @wraps(method)
    def read(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return read


class EventDatabase:
    """
    Persistent SQLite event store.

    Thread-safe: uses a threading.Lock around write operations so the
    detection loop (writer) and API server (reader) can coexist safely.
    """

    def __init__(
        self,
        database_path: str = "data/sentinelai.db",
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

        self.connection = sqlite3.connect(
            str(self.database_path),
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        # Enable WAL mode so readers (API) don't block writers (detection loop)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")

        self._create_table()
        self._migrate()

    # ======================================
    # SCHEMA
    # ======================================

    def _create_table(self) -> None:
        with self._lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type     TEXT    NOT NULL,
                    track_id       INTEGER NOT NULL,
                    class_name     TEXT    NOT NULL,
                    timestamp      TEXT    NOT NULL,
                    zone           TEXT,
                    confidence     REAL    NOT NULL DEFAULT 1.0,
                    description    TEXT    NOT NULL DEFAULT '',
                    evidence_path  TEXT,
                    vlm_answer     TEXT,
                    vlm_raw_text   TEXT,
                    vlm_adapter    INTEGER
                )
                """
            )
            self.connection.commit()

    def _migrate(self) -> None:
        """Add columns introduced after initial schema without dropping data."""
        existing = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(events)")
        }
        additions = {
            "vlm_duration_ms": "REAL",
            "vlm_task": "TEXT",
            "vlm_evidence_sha256": "TEXT",
            "source_metadata": "TEXT",
            "vlm_status": "TEXT",
            "vlm_prompt": "TEXT",
            "vlm_model_id": "TEXT",
            "vlm_checked_at": "TEXT",
            "vlm_error": "TEXT",
            "vlm_answer":   "TEXT",
            "vlm_raw_text": "TEXT",
            "vlm_adapter":  "INTEGER",
            "evidence_path": "TEXT",
        }
        with self._lock:
            for col, col_type in additions.items():
                if col not in existing:
                    self.connection.execute(
                        f"ALTER TABLE events ADD COLUMN {col} {col_type}"
                    )
                    logger.info("Migrated DB: added column '%s'", col)
            self.connection.commit()

    # ======================================
    # WRITE
    # ======================================

    def save_event(
        self,
        event: Event,
        evidence_path: str | None = None,
        source_metadata: dict | None = None,
    ) -> int:
        """
        Persist a new event and return its auto-incremented ID.
        """
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT INTO events (
                    event_type, track_id, class_name, timestamp,
                    zone, confidence, description, evidence_path, source_metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.track_id,
                    event.class_name,
                    event.timestamp.isoformat(),
                    event.zone,
                    event.confidence,
                    event.description,
                    evidence_path,
                    json.dumps(source_metadata) if source_metadata is not None else None,
                ),
            )
            self.connection.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def update_vlm_result(
        self,
        event_id: int,
        vlm_answer: str,
        vlm_raw_text: str,
        adapter_loaded: bool,
        error: str | None = None,
    ) -> None:
        """
        Update the VLM verification result for an existing event.
        Called asynchronously by the EventVerifier worker thread.
        """
        with self._lock:
            self.connection.execute(
                """
                UPDATE events
                SET vlm_answer = ?, vlm_raw_text = ?, vlm_adapter = ?, vlm_error = ?
                WHERE id = ?
                """,
                (vlm_answer, vlm_raw_text, int(adapter_loaded), error, event_id),
            )
            self.connection.commit()

    def update_evidence_path(
        self,
        event_id: int,
        evidence_path: str,
    ) -> None:
        """Update the evidence path for an existing event."""
        with self._lock:
            self.connection.execute(
                "UPDATE events SET evidence_path = ? WHERE id = ?",
                (evidence_path, event_id),
            )
            self.connection.commit()

    # ======================================
    # READ
    # ======================================

    @serialized_read
    def get_recent_events(
        self,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT id, event_type, track_id, class_name, timestamp,
                   zone, confidence, description, evidence_path,
                   vlm_answer, vlm_raw_text, vlm_adapter, vlm_error,
                   vlm_status, vlm_prompt, vlm_model_id, vlm_checked_at, vlm_task, vlm_evidence_sha256, vlm_duration_ms, source_metadata
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cursor.fetchall()

    @serialized_read
    def get_events_by_type(
        self,
        event_type: str,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT id, event_type, track_id, class_name, timestamp,
                   zone, confidence, description, evidence_path,
                   vlm_answer, vlm_raw_text, vlm_adapter, vlm_error,
                   vlm_status, vlm_prompt, vlm_model_id, vlm_checked_at, vlm_task, vlm_evidence_sha256, vlm_duration_ms, source_metadata
            FROM events
            WHERE event_type = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (event_type, limit),
        )
        return cursor.fetchall()

    @serialized_read
    def get_event_by_id(self, event_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT id, event_type, track_id, class_name, timestamp,
                   zone, confidence, description, evidence_path,
                   vlm_answer, vlm_raw_text, vlm_adapter, vlm_error,
                   vlm_status, vlm_prompt, vlm_model_id, vlm_checked_at, vlm_task, vlm_evidence_sha256, vlm_duration_ms, source_metadata
            FROM events
            WHERE id = ?
            """,
            (event_id,),
        )
        return cursor.fetchone()

    @serialized_read
    def search_events(
        self,
        query: str,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        """Full-text search over the description column."""
        cursor = self.connection.execute(
            """
            SELECT id, event_type, track_id, class_name, timestamp,
                   zone, confidence, description, evidence_path,
                   vlm_answer, vlm_raw_text, vlm_adapter, vlm_error,
                   vlm_status, vlm_prompt, vlm_model_id, vlm_checked_at, vlm_task, vlm_evidence_sha256, vlm_duration_ms, source_metadata
            FROM events
            WHERE description LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        return cursor.fetchall()

    @serialized_read
    def get_events_in_range(
        self,
        start_iso: str,
        end_iso: str,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT id, event_type, track_id, class_name, timestamp,
                   zone, confidence, description, evidence_path,
                   vlm_answer, vlm_raw_text, vlm_adapter, vlm_error,
                   vlm_status, vlm_prompt, vlm_model_id, vlm_checked_at, vlm_task, vlm_evidence_sha256, vlm_duration_ms, source_metadata
            FROM events
            WHERE julianday(timestamp) >= julianday(?) AND julianday(timestamp) <= julianday(?)
            ORDER BY id DESC
            LIMIT ?
            """,
            (start_iso, end_iso, limit),
        )
        return cursor.fetchall()

    @serialized_read
    def count_events(self) -> int:
        cursor = self.connection.execute("SELECT COUNT(*) FROM events")
        return cursor.fetchone()[0]

    @serialized_read
    def count_by_type(self) -> dict[str, int]:
        cursor = self.connection.execute(
            """
            SELECT event_type, COUNT(*) AS n
            FROM events
            GROUP BY event_type
            ORDER BY n DESC
            """
        )
        return {row["event_type"]: row["n"] for row in cursor.fetchall()}

    # ======================================
    # LIFECYCLE
    # ======================================

    def close(self) -> None:
        self.connection.close()
        logger.info("EventDatabase closed.")

    def __repr__(self) -> str:
        return f"EventDatabase(path={self.database_path!r})"
    def set_verification(self, event_id, status, prompt, model_id, answer=None,
                         raw_text=None, adapter_loaded=None, error=None, task=None,
                         evidence_sha256=None, duration_ms=None):
        from datetime import datetime, timezone
        with self._lock:
            self.connection.execute("""
                UPDATE events SET vlm_status=?, vlm_prompt=?, vlm_model_id=?,
                vlm_answer=?, vlm_raw_text=?, vlm_adapter=?, vlm_error=?, vlm_checked_at=?,
                vlm_task=?, vlm_evidence_sha256=?, vlm_duration_ms=?
                WHERE id=?
            """, (status,prompt,model_id,answer,raw_text,
                  None if adapter_loaded is None else int(adapter_loaded),error,
                  datetime.now(timezone.utc).isoformat(),task,evidence_sha256,duration_ms,event_id))
            self.connection.commit()

    def query_events(self, limit=20, event_type=None, start=None, end=None,
                     event_id=None, with_vlm=False, source_kind=None,
                     source_device_id=None, evidence_source=None):
        clauses, params = [], []
        for column,value in (("event_type",event_type),("id",event_id)):
            if value is not None:
                clauses.append(column+" = ?");params.append(value)
        if start:
            clauses.append("julianday(timestamp) >= julianday(?)");params.append(start)
        if end:
            clauses.append("julianday(timestamp) <= julianday(?)");params.append(end)
        if with_vlm:
            clauses.append("(vlm_raw_text IS NOT NULL OR vlm_status IN ('inconclusive','error'))")
        # Filter before LIMIT so a newer webcam row cannot displace camera evidence.
        for key,value in (("source_kind",source_kind),("device_id",source_device_id),("evidence_source",evidence_source)):
            if value is not None:
                clauses.append("json_extract(CASE WHEN json_valid(source_metadata) THEN source_metadata ELSE '{}' END, '$."+key+"') = ?")
                params.append(value)
        where = " WHERE "+" AND ".join(clauses) if clauses else ""
        with self._lock:
            rows=self.connection.execute(
                "SELECT * FROM events"+where+" ORDER BY julianday(timestamp) DESC, id DESC LIMIT ?",
                params+[max(1,min(int(limit),100))]).fetchall()
        return rows
