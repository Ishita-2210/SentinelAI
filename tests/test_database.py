# tests/test_database.py
"""Tests for EventDatabase and EventRetriever."""
import pytest
from datetime import datetime
from backend.schemas.event import Event
from backend.database.event_database import EventDatabase
from backend.retrival.retrival import EventRetriever


def test_save_and_retrieve(tmp_db, sample_event):
    eid = tmp_db.save_event(sample_event, evidence_path="/data/test.jpg")
    assert isinstance(eid, int)
    assert eid >= 1

    row = tmp_db.get_event_by_id(eid)
    assert row is not None
    assert row["event_type"] == "LOITERING"
    assert row["track_id"] == 1
    assert row["zone"] == "entrance"
    assert row["evidence_path"] == "/data/test.jpg"
    assert row["vlm_answer"] is None


def test_vlm_update(tmp_db, sample_event):
    eid = tmp_db.save_event(sample_event)
    tmp_db.update_vlm_result(eid, "yes", "yes the person is loitering", True)

    row = tmp_db.get_event_by_id(eid)
    assert row["vlm_answer"] == "yes"
    assert row["vlm_raw_text"] == "yes the person is loitering"
    assert row["vlm_adapter"] == 1


def test_get_recent(tmp_db, sample_event):
    for _ in range(5):
        tmp_db.save_event(sample_event)

    rows = tmp_db.get_recent_events(limit=3)
    assert len(rows) == 3


def test_get_by_type(tmp_db):
    from backend.schemas.event import Event
    from datetime import datetime

    ev1 = Event("LOITERING", 1, "person", datetime.now(), description="test")
    ev2 = Event("RUNNING", 2, "person", datetime.now(), description="test")
    tmp_db.save_event(ev1)
    tmp_db.save_event(ev2)

    loitering = tmp_db.get_events_by_type("LOITERING")
    assert len(loitering) == 1
    assert loitering[0]["event_type"] == "LOITERING"


def test_count(tmp_db, sample_event):
    assert tmp_db.count_events() == 0
    tmp_db.save_event(sample_event)
    tmp_db.save_event(sample_event)
    assert tmp_db.count_events() == 2


def test_count_by_type(tmp_db):
    from datetime import datetime
    ev_l = Event("LOITERING", 1, "person", datetime.now())
    ev_r = Event("RUNNING", 2, "person", datetime.now())
    tmp_db.save_event(ev_l)
    tmp_db.save_event(ev_l)
    tmp_db.save_event(ev_r)

    counts = tmp_db.count_by_type()
    assert counts["LOITERING"] == 2
    assert counts["RUNNING"] == 1


def test_retriever_get_recent(tmp_db, sample_event):
    tmp_db.save_event(sample_event)
    retriever = EventRetriever(tmp_db)
    events = retriever.get_recent(limit=10)
    assert len(events) == 1
    assert isinstance(events[0], dict)
    assert events[0]["event_type"] == "LOITERING"


def test_retriever_stats(tmp_db, sample_event):
    tmp_db.save_event(sample_event)
    retriever = EventRetriever(tmp_db)
    stats = retriever.get_stats()
    assert stats["total"] == 1
    assert "LOITERING" in stats["by_type"]


def test_retriever_search(tmp_db):
    from datetime import datetime
    ev = Event("LOITERING", 1, "person", datetime.now(),
               description="person loitering near entrance gate")
    tmp_db.save_event(ev)

    retriever = EventRetriever(tmp_db)
    results = retriever.search("entrance")
    assert len(results) == 1
    results_empty = retriever.search("xyz_not_found")
    assert len(results_empty) == 0


def test_migrate_is_idempotent(tmp_path):
    """Opening DB twice should not error (migration is additive)."""
    path = str(tmp_path / "idempotent.db")
    db1 = EventDatabase(database_path=path)
    db1.close()
    db2 = EventDatabase(database_path=path)
    db2.close()
