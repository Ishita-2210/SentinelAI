import sqlite3
from pathlib import Path

from backend.schemas.event import Event


class EventDatabase:

    def __init__(
        self,
        database_path: str = "data/sentinelai.db",
    ):
        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            self.database_path
        )

        self.connection.row_factory = sqlite3.Row

        self.create_table()

    # ======================================
    # CREATE TABLE
    # ======================================

    def create_table(self):

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                zone TEXT,
                confidence REAL NOT NULL,
                description TEXT NOT NULL,
                evidence_path TEXT
            )
            """
        )

        self.connection.commit()

    # ======================================
    # SAVE EVENT
    # ======================================

    def save_event(
        self,
        event: Event,
        evidence_path: str | None = None,
    ) -> int:

        cursor = self.connection.execute(
            """
            INSERT INTO events (
                event_type,
                track_id,
                class_name,
                timestamp,
                zone,
                confidence,
                description,
                evidence_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

        self.connection.commit()

        return cursor.lastrowid

    # ======================================
    # GET RECENT EVENTS
    # ======================================

    def get_recent_events(
        self,
        limit: int = 20,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT
                id,
                event_type,
                track_id,
                class_name,
                timestamp,
                zone,
                confidence,
                description,
                evidence_path
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return cursor.fetchall()

    # ======================================
    # GET EVENTS BY TYPE
    # ======================================

    def get_events_by_type(
        self,
        event_type: str,
        limit: int = 20,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            """
            SELECT
                id,
                event_type,
                track_id,
                class_name,
                timestamp,
                zone,
                confidence,
                description,
                evidence_path
            FROM events
            WHERE event_type = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                event_type,
                limit,
            ),
        )

        return cursor.fetchall()

    # ======================================
    # COUNT EVENTS
    # ======================================

    def count_events(self) -> int:

        cursor = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM events
            """
        )

        return cursor.fetchone()[0]

    # ======================================
    # CLOSE DATABASE
    # ======================================

    def close(self):

        self.connection.close()