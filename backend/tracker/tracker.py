"""
SentinelAI — Tracker

Uses YOLO's built-in ByteTrack tracker (bundled with ultralytics),
which avoids the `supervision.ByteTrack` API that was removed in
supervision 0.26+.

The public interface is identical to the original:
    tracker = Tracker()
    tracks = tracker.update(frame, detections)

NOTE: The signature changed — we now pass the raw frame because YOLO's
tracker needs it to produce IDs. The Detector is bypassed here;
instead, the Tracker runs detection + tracking in one call.

For the main pipeline, use TrackerDetector which wraps both.
"""
from __future__ import annotations

import logging
import os
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
from pathlib import Path

import numpy as np
from ultralytics import YOLO

from backend.schemas.bounding_box import BoundingBox
from backend.schemas.detection import Detection
from backend.schemas.track import Track

logger = logging.getLogger(__name__)


class Tracker:
    """
    Wraps YOLO's built-in ByteTrack for persistent object IDs.

    Args:
        model_path:            YOLO model file (e.g. yolo11n.pt).
        confidence_threshold:  Minimum detection confidence.
        tracker_config:        YOLO tracker config name ('bytetrack.yaml' default).

    Usage:
        tracker = Tracker()
        tracks = tracker.update(frame)   # frame is a numpy BGR array
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.5,
        tracker_config: str = "bytetrack.yaml",
        iou_threshold: float = 0.7,
        device: str = "auto",
    ) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"YOLO weights not found: {model_path}")
        import importlib.util
        if importlib.util.find_spec("lap") is None:
            raise RuntimeError("ByteTrack needs lap; install the pinned core requirements")
        self.model = YOLO(model_path)
        self.iou_threshold = iou_threshold
        self.device = None if device == "auto" else device
        self.confidence_threshold = confidence_threshold
        self.tracker_config = tracker_config
        self._names: dict[int, str] = self.model.names

    def update(self, frame: np.ndarray) -> list[Track]:
        """
        Run detection + ByteTrack on a single frame.

        Args:
            frame: BGR numpy array from OpenCV.

        Returns:
            List of Track objects with persistent track_ids.
            Returns empty list if no tracks.
        """
        self._validate_frame(frame)
        results = self.model.track(
            frame,
            persist=True,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            tracker=self.tracker_config,
            verbose=False,
        )

        tracks: list[Track] = []

        if results is None or len(results) == 0:
            return tracks

        result = results[0]

        if result.boxes is None or result.boxes.id is None:
            # No tracks assigned (first frame or no objects)
            return tracks

        for box, track_id in zip(result.boxes, result.boxes.id):
            if track_id is None:
                continue

            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()

            track = Track(
                track_id=int(track_id),
                class_id=class_id,
                class_name=self._names[class_id],
                confidence=confidence,
                bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
            )
            tracks.append(track)

        return tracks

    def reset(self) -> None:
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", []):
            tracker.reset()

    def detect_only(self, frame: np.ndarray) -> list[Detection]:
        """
        Run detection without tracking (no track IDs).
        Used by the Detector wrapper for backward compatibility.
        """
        self._validate_frame(frame)
        results = self.model(
            frame,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )
        detections: list[Detection] = []
        if not results or results[0].boxes is None:
            return detections
        for box in results[0].boxes:
            class_id = int(box.cls[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(Detection(
                class_id=class_id,
                class_name=self._names[class_id],
                confidence=float(box.conf[0]),
                bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
            ))
        return detections

    @staticmethod
    def _validate_frame(frame):
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError("YOLO requires a nonempty uint8 HxWx3 BGR frame")
