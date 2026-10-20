# tests/test_evidence.py
"""Tests for KeyframeCapture — uses synthetic numpy frames, no camera needed."""
import numpy as np
import cv2
import pytest
from datetime import datetime
from pathlib import Path
from backend.evidence.keyframe_capture import KeyframeCapture


@pytest.fixture()
def capture(tmp_path):
    return KeyframeCapture(output_dir=str(tmp_path / "events"))


def _blank_frame(h=480, w=640):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_save_creates_file(capture, tmp_path):
    frame = _blank_frame()
    ts = datetime(2026, 10, 19, 12, 0, 0)
    path = capture.save(frame, "LOITERING", track_id=1, timestamp=ts)
    assert Path(path).exists()


def test_filename_contains_event_type(capture):
    frame = _blank_frame()
    ts = datetime(2026, 10, 19, 12, 0, 0)
    path = capture.save(frame, "RUNNING", track_id=7, timestamp=ts)
    assert "RUNNING" in Path(path).name
    assert "track_7" in Path(path).name


def test_save_returns_valid_jpeg(capture):
    frame = _blank_frame()
    ts = datetime.now()
    path = capture.save(frame, "PERSON_ENTERED", track_id=3, timestamp=ts)
    loaded = cv2.imread(path)
    assert loaded is not None
    assert loaded.shape[2] == 3


def test_output_dir_created_automatically(tmp_path):
    nested = str(tmp_path / "a" / "b" / "c")
    kc = KeyframeCapture(output_dir=nested)
    frame = _blank_frame()
    path = kc.save(frame, "TEST", track_id=1, timestamp=datetime.now())
    assert Path(path).exists()
