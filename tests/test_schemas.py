# tests/test_schemas.py
"""Tests for schema dataclasses."""
from backend.schemas.bounding_box import BoundingBox
from backend.schemas.detection import Detection
from backend.schemas.track import Track
from backend.schemas.event import Event
from backend.schemas.object_state import ObjectState
from datetime import datetime


def test_bounding_box_center():
    box = BoundingBox(x1=0, y1=0, x2=200, y2=100)
    cx, cy = box.center
    assert cx == 100.0
    assert cy == 50.0


def test_bounding_box_dimensions():
    box = BoundingBox(x1=10, y1=20, x2=110, y2=70)
    assert box.width == 100.0
    assert box.height == 50.0


def test_detection_creation():
    box = BoundingBox(0, 0, 100, 100)
    d = Detection(class_id=0, class_name="person", confidence=0.9, bounding_box=box)
    assert d.class_name == "person"
    assert d.confidence == 0.9


def test_track_creation():
    box = BoundingBox(0, 0, 50, 50)
    t = Track(track_id=42, class_id=0, class_name="car", confidence=0.8, bounding_box=box)
    assert t.track_id == 42


def test_event_defaults():
    ev = Event(
        event_type="RUNNING",
        track_id=5,
        class_name="person",
        timestamp=datetime.now(),
    )
    assert ev.zone is None
    assert ev.confidence == 1.0
    assert ev.description == ""


def test_object_state_defaults():
    box = BoundingBox(0, 0, 100, 100)
    s = ObjectState(track_id=1, class_id=0, class_name="person", current_box=box)
    assert s.status == "ACTIVE"
    assert s.loitering is False
    assert s.running is False
    assert s.unattended is False
    assert s.velocity == (0.0, 0.0)
