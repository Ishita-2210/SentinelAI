# tests/test_event_engine.py
"""
Tests for StateManager + EventEngine.
No camera, no model — uses fake tracks with injected timestamps.

REAL-PIPELINE CONTRACT: The event engine (ee) must always receive the
states produced by the state manager (sm) for the same frame. Passing
empty states to ee while sm saw objects is NOT a valid call in the
real pipeline and will confuse zone/exit tracking.  These tests now
simulate the pipeline correctly.
"""
import pytest
from datetime import datetime, timedelta
from backend.schemas.bounding_box import BoundingBox
from backend.schemas.track import Track
from backend.state_manager.state_manager import StateManager
from backend.event_engine.event_engine import EventEngine


def _make_track(tid: int, x1: float, y1: float, x2: float, y2: float,
                class_name: str = "person") -> Track:
    return Track(
        track_id=tid,
        class_id=0,
        class_name=class_name,
        confidence=0.95,
        bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
    )


def _run_frame(sm, ee, tracks, timestamp):
    """Run one full pipeline frame: sm.update → ee.update → return events."""
    states = sm.update(tracks, timestamp)
    return ee.update(states, timestamp)


@pytest.fixture()
def pipeline():
    sm = StateManager()
    ee = EventEngine()
    # Lower thresholds so we don't need many seconds of simulated time
    ee.loitering_threshold = 5.0
    ee.running_threshold = 20.0
    ee.unattended_threshold = 3.0
    ee.association_distance = 300.0
    ee.separation_distance = 200.0
    return sm, ee


T0 = datetime(2026, 10, 19, 12, 0, 0)


def test_person_entered_on_first_appearance(pipeline):
    sm, ee = pipeline
    track = _make_track(1, 100, 100, 200, 300)
    events = _run_frame(sm, ee, [track], T0)
    types = [e.event_type for e in events]
    assert "PERSON_ENTERED" in types


def test_loitering_triggered_after_threshold(pipeline):
    """
    Person appears in frame 0, stays for 6 seconds.
    LOITERING must fire in frame 1 (6s > 5s threshold).

    The correct pipeline call is: sm.update then ee.update with the
    SAME states for every frame, including frame 0.
    """
    sm, ee = pipeline
    track = _make_track(1, 100, 100, 200, 300)

    # Frame 0 — object appears; PERSON_ENTERED fires, zone_entered_at set
    _run_frame(sm, ee, [track], T0)

    # Frame 1 — 6 seconds later
    t1 = T0 + timedelta(seconds=6)
    events = _run_frame(sm, ee, [track], t1)
    types = [e.event_type for e in events]
    assert "LOITERING" in types, f"Got events: {types}"


def test_loitering_not_triggered_before_threshold(pipeline):
    sm, ee = pipeline
    track = _make_track(1, 100, 100, 200, 300)

    # Frame 0
    _run_frame(sm, ee, [track], T0)

    # Only 2 seconds — below 5s threshold
    t1 = T0 + timedelta(seconds=2)
    events = _run_frame(sm, ee, [track], t1)
    types = [e.event_type for e in events]
    assert "LOITERING" not in types


def test_running_triggered_by_high_velocity(pipeline):
    """
    Person moves 30 px/frame — above 20 px threshold.
    Collect events across all frames; RUNNING must appear at least once.
    """
    sm, ee = pipeline

    all_events = []

    # Frame 0 — person appears stationary
    all_events += _run_frame(sm, ee, [_make_track(1, 100, 100, 200, 300)], T0)

    # Frames 1-3 — person moves 30px/frame
    for i in range(1, 4):
        t2 = _make_track(1, 100 + i * 30, 100, 200 + i * 30, 300)
        t_now = T0 + timedelta(seconds=i * 0.033)
        all_events += _run_frame(sm, ee, [t2], t_now)

    types = [e.event_type for e in all_events]
    assert "RUNNING" in types, f"Got event types across all frames: {types}"


def test_person_exited(pipeline):
    """
    Person appears, is present for two frames, then vanishes.
    PERSON_EXITED must fire on the frame where the track disappears.
    """
    sm, ee = pipeline
    track = _make_track(1, 100, 100, 200, 300)

    # Frame 0 — person appears
    _run_frame(sm, ee, [track], T0)

    # Frame 1 — person still present
    t1 = T0 + timedelta(seconds=1)
    _run_frame(sm, ee, [track], t1)

    # Frame 2 — person gone
    t2 = T0 + timedelta(seconds=2)
    events = _run_frame(sm, ee, [], t2)
    types = [e.event_type for e in events]
    assert "PERSON_EXITED" in types, f"Got events: {types}"


def test_no_duplicate_person_entered(pipeline):
    """PERSON_ENTERED should fire only once per track_id."""
    sm, ee = pipeline
    track = _make_track(1, 100, 100, 200, 300)

    entered_count = 0
    for i in range(5):
        t = T0 + timedelta(seconds=i)
        events = _run_frame(sm, ee, [track], t)
        entered_count += sum(1 for e in events if e.event_type == "PERSON_ENTERED")

    assert entered_count == 1, f"Expected 1 PERSON_ENTERED, got {entered_count}"


def test_state_velocity_computed(pipeline):
    sm, _ = pipeline
    t0 = _make_track(1, 100, 100, 200, 300)
    sm.update([t0], T0)

    t1 = _make_track(1, 150, 100, 250, 300)
    states = sm.update([t1], T0 + timedelta(seconds=0.033))

    state = next(s for s in states if s.track_id == 1)
    vx, vy = state.velocity
    assert vx == pytest.approx(50.0, abs=1.0)  # moved 50px right


def test_event_has_description(pipeline):
    sm, ee = pipeline
    track = _make_track(1, 100, 100, 200, 300)
    events = _run_frame(sm, ee, [track], T0)
    for ev in events:
        assert isinstance(ev.description, str)
        assert len(ev.description) > 0


def test_running_resets_and_refires(pipeline):
    """
    Person runs, slows down, then runs again.
    RUNNING should fire both times.
    """
    sm, ee = pipeline
    all_events = []

    # Frame 0 — appears stationary
    all_events += _run_frame(sm, ee, [_make_track(1, 100, 100, 200, 300)], T0)

    # Frame 1 — running (30px/frame > 20 threshold)
    all_events += _run_frame(sm, ee, [_make_track(1, 130, 100, 230, 300)],
                             T0 + timedelta(seconds=0.033))

    # Frame 2 — slow (2px/frame < 20 threshold) — resets running flag
    all_events += _run_frame(sm, ee, [_make_track(1, 132, 100, 232, 300)],
                             T0 + timedelta(seconds=0.066))

    # Frame 3 — running again
    all_events += _run_frame(sm, ee, [_make_track(1, 162, 100, 262, 300)],
                             T0 + timedelta(seconds=0.099))

    running_events = [e for e in all_events if e.event_type == "RUNNING"]
    assert len(running_events) >= 2, (
        f"Expected RUNNING to fire at least twice, got {len(running_events)}"
    )


def test_loitering_resets_on_zone_change(pipeline):
    """After a zone change, loitering timer should reset."""
    sm, ee = pipeline

    # Frame 0 — enter zone "entrance" (0..1000, 0..1000)
    track_in = _make_track(1, 100, 100, 200, 300)
    _run_frame(sm, ee, [track_in], T0)

    # Add a second zone to the engine
    from backend.event_engine.zone import Zone
    ee.zones.append(Zone(name="exit", x1=1001, y1=0, x2=2000, y2=1000))

    # Frame 1 — person in entrance for 6s → loiters
    t1 = T0 + timedelta(seconds=6)
    events1 = _run_frame(sm, ee, [track_in], t1)
    types1 = [e.event_type for e in events1]
    assert "LOITERING" in types1

    # Frame 2 — person moves to exit zone; loitering should NOT fire again
    track_exit = _make_track(1, 1100, 100, 1200, 300)
    t2 = T0 + timedelta(seconds=7)
    events2 = _run_frame(sm, ee, [track_exit], t2)
    types2 = [e.event_type for e in events2]
    assert "ZONE_CHANGED" in types2
    assert "LOITERING" not in types2
