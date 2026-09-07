import numpy as np
import supervision as sv

from backend.schemas.detection import Detection
from backend.schemas.track import Track


class Tracker:

    def __init__(self):
        self.tracker = sv.ByteTrack()

    def update(self, detections: list[Detection]) -> list[Track]:
        """
        Update ByteTrack using the detections from the current frame.

        Args:
            detections: Detections produced by YOLO.

        Returns:
            A list of Track objects with persistent track IDs.
        """

        if not detections:
            return []

        # Convert our Detection objects into arrays
        xyxy = np.array([
            [
                detection.bounding_box.x1,
                detection.bounding_box.y1,
                detection.bounding_box.x2,
                detection.bounding_box.y2,
            ]
            for detection in detections
        ], dtype=np.float32)

        confidence = np.array(
            [detection.confidence for detection in detections],
            dtype=np.float32,
        )

        class_id = np.array(
            [detection.class_id for detection in detections],
            dtype=int,
        )

        # Create Supervision detections
        supervision_detections = sv.Detections(
            xyxy=xyxy,
            confidence=confidence,
            class_id=class_id,
        )

        # Run ByteTrack
        tracked_detections = self.tracker.update_with_detections(
            supervision_detections
        )

        tracks = []

        for i, track_id in enumerate(tracked_detections.tracker_id):

            if track_id is None:
                continue

            original_detection = detections[i]

            track = Track(
                track_id=int(track_id),
                class_id=original_detection.class_id,
                class_name=original_detection.class_name,
                confidence=original_detection.confidence,
                bounding_box=original_detection.bounding_box,
            )

            tracks.append(track)

        return tracks