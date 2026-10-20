from datetime import datetime
from pathlib import Path
import re
import uuid

import cv2


class KeyframeCapture:

    def __init__(
        self,
        output_dir: str = "data/events",
    ):
        self.output_dir = Path(output_dir)

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def save(
        self,
        frame,
        event_type: str,
        track_id: int,
        timestamp: datetime,
    ) -> str:

        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", event_type):
            raise ValueError("Invalid evidence event type")

        timestamp_text = timestamp.strftime(
            "%Y%m%d_%H%M%S_%f"
        )[:-3]

        filename = (
            f"{timestamp_text}_"
            f"{event_type}_"
            f"track_{track_id}_{uuid.uuid4().hex}.jpg"
        )

        file_path = self.output_dir / filename

        success = cv2.imwrite(
            str(file_path),
            frame,
        )

        if not success:
            raise RuntimeError(
                f"Failed to save keyframe: {file_path}"
            )

        return str(file_path)
