"""Bridge between the pipeline process and the API process.

The pipeline publishes its latest annotated frame and a small status file;
the API streams them to the dashboard. Files are written atomically so the
reader never sees a half-written frame.
"""

import json
import os
import time
from pathlib import Path

import cv2


class LiveFeed:

    def __init__(
        self,
        directory: str = "data/live",
        max_fps: float = 5.0,
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

        self.frame_path = self.directory / "latest.jpg"
        self.status_path = self.directory / "status.json"

        self._min_interval = 1.0 / max_fps
        self._last_publish = 0.0

    def publish(self, frame, status: dict) -> bool:
        """Write the frame and status if enough time has passed."""

        now = time.monotonic()

        if now - self._last_publish < self._min_interval:
            return False

        self._last_publish = now

        ok, encoded = cv2.imencode(".jpg", frame)

        if ok:
            self._atomic_write(self.frame_path, encoded.tobytes())

        status = {**status, "updated_at": time.time()}

        self._atomic_write(
            self.status_path,
            json.dumps(status).encode("utf-8"),
        )

        return True

    @staticmethod
    def _atomic_write(path: Path, data: bytes):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
