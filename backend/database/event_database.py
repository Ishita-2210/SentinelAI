import sqlite3
from datetime import datetime
from pathlib import Path

from backend.schemas.event import Event


EVENT_COLUMNS = """
    id,
    event_type,
    track_id,
    class_name,
    timestamp,
    zone,
    confidence,
    description,
    evidence_path,
    verification,
    verification_detail,
    alerted
"""


class EventDatabase:

    def __init__(
        self,
        database_path: str = "data/sentinelai.db",
        check_same_thread: bool = True,
    ):
        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=check_same_thread,
        )

        self.connection.row_factory = sqlite3.Row

        # WAL lets the API read while the pipeline writes.
        self.connection.execute("PRAGMA journal_mode=WAL")

        self.fts_enabled = False

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

        self._migrate()
        self._init_fts()

        self.connection.commit()

    def _migrate(self):
        """Add columns introduced after the first release.

        Databases created by older versions keep working: missing
        columns are added in place and existing rows are untouched.
        """

        existing = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(events)"
            )
        }

        additions = {
            # YES / NO / UNKNOWN from the VLM, NULL = not verified yet
            "verification": "TEXT",
            "verification_detail": "TEXT",
            "alerted": "INTEGER NOT NULL DEFAULT 0",
        }

        for column, definition in additions.items():
            if column not in existing:
                self.connection.execute(
                    f"ALTER TABLE events ADD COLUMN {column} {definition}"
                )

    def _init_fts(self):
        """Full-text index used by the retrieval layer (SQLite FTS5)."""

        try:
            fts_exists = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'events_fts'"
            ).fetchone() is not None

            self.connection.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                    event_type,
                    class_name,
                    zone,
                    description,
                    verification_detail,
                    content='events',
                    content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS events_ai
                AFTER INSERT ON events BEGIN
                    INSERT INTO events_fts(
                        rowid, event_type, class_name, zone,
                        description, verification_detail
                    ) VALUES (
                        new.id, new.event_type, new.class_name, new.zone,
                        new.description, new.verification_detail
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS events_ad
                AFTER DELETE ON events BEGIN
                    INSERT INTO events_fts(
                        events_fts, rowid, event_type, class_name, zone,
                        description, verification_detail
                    ) VALUES (
                        'delete', old.id, old.event_type, old.class_name,
                        old.zone, old.description, old.verification_detail
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS events_au
                AFTER UPDATE ON events BEGIN
                    INSERT INTO events_fts(
                        events_fts, rowid, event_type, class_name, zone,
                        description, verification_detail
                    ) VALUES (
                        'delete', old.id, old.event_type, old.class_name,
                        old.zone, old.description, old.verification_detail
                    );
                    INSERT INTO events_fts(
                        rowid, event_type, class_name, zone,
                        description, verification_detail
                    ) VALUES (
                        new.id, new.event_type, new.class_name, new.zone,
                        new.description, new.verification_detail
                    );
                END;
                """
            )

            # Index rows that existed before FTS was created (only needed
            # the first time; the triggers keep it in sync afterwards).
            if not fts_exists:
                self.connection.execute(
                    "INSERT INTO events_fts(events_fts) VALUES('rebuild')"
                )

            self.fts_enabled = True

        except sqlite3.OperationalError:
            # SQLite built without FTS5: retrieval falls back to LIKE.
            self.fts_enabled = False

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
    # UPDATE EVENT
    # ======================================

    def update_evidence(
        self,
        event_id: int,
        evidence_path: str,
    ):
        self.connection.execute(
            "UPDATE events SET evidence_path = ? WHERE id = ?",
            (evidence_path, event_id),
        )
        self.connection.commit()

    def update_verification(
        self,
        event_id: int,
        verdict: str,
        detail: str,
    ):
        self.connection.execute(
            """
            UPDATE events
            SET verification = ?, verification_detail = ?
            WHERE id = ?
            """,
            (verdict, detail, event_id),
        )
        self.connection.commit()

    def mark_alerted(self, event_id: int):
        self.connection.execute(
            "UPDATE events SET alerted = 1 WHERE id = ?",
            (event_id,),
        )
        self.connection.commit()

    # ======================================
    # GET EVENTS
    # ======================================

    def get_event(self, event_id: int) -> sqlite3.Row | None:

        cursor = self.connection.execute(
            f"SELECT {EVENT_COLUMNS} FROM events WHERE id = ?",
            (event_id,),
        )

        return cursor.fetchone()

    def get_recent_events(
        self,
        limit: int = 20,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

        return cursor.fetchall()

    def get_events_by_type(
        self,
        event_type: str,
        limit: int = 20,
    ) -> list[sqlite3.Row]:

        cursor = self.connection.execute(
            f"""
            SELECT {EVENT_COLUMNS}
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

    def query_events(
        self,
        event_type: str | None = None,
        zone: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        """Filtered event listing, newest first."""

        clauses = []
        params: list = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)

        if zone:
            clauses.append("zone = ?")
            params.append(zone)

        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        if until:
            clauses.append("timestamp <= ?")
            params.append(until.isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        params.append(limit)

        cursor = self.connection.execute(
            f"""
            SELECT {EVENT_COLUMNS}
            FROM events
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        )

        return cursor.fetchall()

    # ======================================
    # COUNT / STATS
    # ======================================

    def count_events(self) -> int:

        cursor = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM events
            """
        )

        return cursor.fetchone()[0]

    def count_by_type(self) -> dict[str, int]:

        cursor = self.connection.execute(
            """
            SELECT event_type, COUNT(*) AS total
            FROM events
            GROUP BY event_type
            """
        )

        return {row["event_type"]: row["total"] for row in cursor}

    # ======================================
    # CLOSE DATABASE
    # ======================================

    def close(self):

        self.connection.close()
