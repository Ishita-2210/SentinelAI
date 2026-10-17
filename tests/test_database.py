import os
import sqlite3
import tempfile
import unittest

from backend.database.event_database import EventDatabase
from tests.helpers import NOW, add_event


class DatabaseTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "events.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrates_old_database_and_keeps_rows(self):
        # Schema as shipped in the original repo (no verification columns).
        old = sqlite3.connect(self.path)
        old.execute(
            """
            CREATE TABLE events (
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
        old.execute(
            "INSERT INTO events (event_type, track_id, class_name, timestamp,"
            " zone, confidence, description) VALUES"
            " ('LOITERING', 3, 'person', '2026-09-01T10:00:00', 'lobby', 0.8,"
            " 'person lingering near the desk')"
        )
        old.commit()
        old.close()

        database = EventDatabase(self.path)

        row = database.get_event(1)
        self.assertEqual(row["event_type"], "LOITERING")
        self.assertIsNone(row["verification"])
        self.assertEqual(row["alerted"], 0)

        # Rows from before FTS existed are searchable.
        hits = database.connection.execute(
            "SELECT rowid FROM events_fts WHERE events_fts MATCH 'lingering'"
        ).fetchall()
        self.assertEqual([hit[0] for hit in hits], [1])

        database.close()

    def test_reopening_does_not_duplicate_or_fail(self):
        first = EventDatabase(self.path)
        add_event(first)
        first.close()

        second = EventDatabase(self.path)
        self.assertEqual(second.count_events(), 1)
        second.close()

    def test_verification_update_is_indexed(self):
        database = EventDatabase(self.path)
        event_id = add_event(database)

        database.update_verification(event_id, "YES", "bag is on the floor alone")

        hits = database.connection.execute(
            "SELECT rowid FROM events_fts WHERE events_fts MATCH 'floor'"
        ).fetchall()
        self.assertEqual([hit[0] for hit in hits], [event_id])

        row = database.get_event(event_id)
        self.assertEqual(row["verification"], "YES")

        database.close()

    def test_mark_alerted_and_evidence(self):
        database = EventDatabase(self.path)
        event_id = add_event(database)

        database.mark_alerted(event_id)
        database.update_evidence(event_id, "data/events/x.jpg")

        row = database.get_event(event_id)
        self.assertEqual(row["alerted"], 1)
        self.assertEqual(row["evidence_path"], "data/events/x.jpg")

        database.close()

    def test_query_filters(self):
        database = EventDatabase(self.path)

        add_event(database, "UNATTENDED_OBJECT", minutes_ago=5, zone="entrance")
        add_event(database, "LOITERING", class_name="person", minutes_ago=50, zone="lobby")
        add_event(database, "LOITERING", class_name="person", minutes_ago=500, zone="lobby")

        self.assertEqual(len(database.query_events(event_type="LOITERING")), 2)
        self.assertEqual(len(database.query_events(zone="entrance")), 1)

        from datetime import timedelta

        recent = database.query_events(since=NOW - timedelta(minutes=60))
        self.assertEqual(len(recent), 2)

        self.assertEqual(
            database.count_by_type(),
            {"UNATTENDED_OBJECT": 1, "LOITERING": 2},
        )

        database.close()


if __name__ == "__main__":
    unittest.main()
