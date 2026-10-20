# tests/conftest.py
"""
Shared fixtures for SentinelAI tests.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parents[1]))


@pytest.fixture()
def tmp_db(tmp_path):
    """Return a fresh EventDatabase backed by a temp file."""
    from backend.config.settings import reset_settings
    reset_settings()

    from backend.database.event_database import EventDatabase
    db_path = str(tmp_path / "test.db")
    db = EventDatabase(database_path=db_path)
    yield db
    db.close()


@pytest.fixture()
def sample_event():
    """Return a minimal Event object."""
    from datetime import datetime
    from backend.schemas.event import Event
    return Event(
        event_type="LOITERING",
        track_id=1,
        class_name="person",
        timestamp=datetime(2026, 10, 19, 12, 0, 0),
        zone="entrance",
        confidence=1.0,
        description="Person loitering for 12 seconds.",
    )


@pytest.fixture()
def bbox():
    from backend.schemas.bounding_box import BoundingBox
    return BoundingBox(x1=100.0, y1=100.0, x2=300.0, y2=400.0)
