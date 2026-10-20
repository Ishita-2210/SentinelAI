"""
SentinelAI — Camera abstraction

Supports:
  - Local webcam (integer index)
  - Video file (for offline testing and demos)
  - ESP32-CAM MJPEG HTTP stream (URL string)

Handles disconnections and failed reads without crashing the caller.
Use as a context manager or call open()/close() explicitly.

Example:
    with CameraSource(source=0, width=1280, height=720) as cam:
        while True:
            ok, frame = cam.read_frame()
            if not ok:
                break
            process(frame)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """Raised when the camera fails to open or consistently fails to read."""


class CameraSource:
    """
    Abstraction over a camera or video stream.

    Args:
        source:
            int  → webcam index (0, 1, …)
            str  → video file path or MJPEG URL (e.g. ESP32-CAM stream)
        width:          Requested capture width (pixels).
        height:         Requested capture height (pixels).
        fps:            Requested capture FPS (webcams only; ignored for files).
        max_failures:   Consecutive failed reads before raising CameraError.
        reconnect_delay_s:
                        Seconds to wait between reconnect attempts.
        loop_video:     If True and source is a video file, loop it.
    """

    def __init__(
        self,
        source: int | str = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        max_failures: int = 10,
        reconnect_delay_s: float = 2.0,
        loop_video: bool = False,
    ) -> None:
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self.max_failures = max_failures
        self.reconnect_delay_s = reconnect_delay_s
        self.loop_video = loop_video

        self._cap: cv2.VideoCapture | None = None
        self._consecutive_failures: int = 0
        self._is_file: bool = self._detect_is_file(source)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_is_file(source: int | str) -> bool:
        if isinstance(source, int):
            return False
        p = Path(source)
        return p.exists() and p.is_file()

    def _open_capture(self) -> cv2.VideoCapture:
        if isinstance(self.source, str) and self.source.startswith(("http://", "https://", "rtsp://")):
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000])
        else:
            cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Failed to open camera source: {self.source!r}"
            )
        if not self._is_file:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
        logger.info(
            "Camera opened: source=%r  %dx%d @ %dfps",
            self.source,
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            int(cap.get(cv2.CAP_PROP_FPS)),
        )
        return cap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the camera/video source. Called automatically by __enter__."""
        self.close()
        self._cap = self._open_capture()
        self._consecutive_failures = 0

    def close(self) -> None:
        """Release the capture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Camera source closed: %r", self.source)

    def read_frame(self) -> tuple[bool, np.ndarray | None]:
        """
        Read a single frame.

        Returns:
            (True, frame)  — success
            (False, None)  — read failed (logged at warning level)

        Raises:
            CameraError: after `max_failures` consecutive failures.
        """
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")

        success, frame = self._cap.read()

        if success and isinstance(frame, np.ndarray) and frame.dtype == np.uint8 and frame.ndim == 3 and frame.shape[2] == 3 and frame.size:
            self._consecutive_failures = 0
            return True, frame

        self._consecutive_failures += 1
        logger.warning(
            "Failed to read frame from %r (failure %d/%d).",
            self.source,
            self._consecutive_failures,
            self.max_failures,
        )

        # Video file at end-of-stream
        if self._is_file:
            if self.loop_video:
                logger.info("Video ended — looping.")
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._consecutive_failures = 0
                ok, frame = self._cap.read()
                if not ok or frame is None or not frame.size:
                    raise CameraError("Looping video has no decodable frames")
                return ok, frame
            else:
                logger.info("Video file finished: %r", self.source)
                return False, None

        if self._consecutive_failures >= self.max_failures:
            logger.error(
                "Camera %r exceeded max consecutive failures (%d). "
                "Attempting reconnect …",
                self.source,
                self.max_failures,
            )
            self._attempt_reconnect()

        return False, None

    def _attempt_reconnect(self) -> None:
        """Try to reopen the camera after failures. Raises CameraError on all failures."""
        self.close()
        time.sleep(self.reconnect_delay_s)
        try:
            self._cap = self._open_capture()
            self._consecutive_failures = 0
            logger.info("Camera reconnected successfully: %r", self.source)
        except CameraError:
            raise CameraError(
                f"Camera source {self.source!r} could not be reopened after "
                f"{self.max_failures} consecutive failures."
            )

    def frames(self) -> Iterator[np.ndarray]:
        """
        Generator that yields frames until the stream ends or raises CameraError.

        Usage:
            for frame in cam.frames():
                process(frame)
        """
        if self._cap is None:
            self.open()
        while True:
            ok, frame = self.read_frame()
            if not ok:
                if self._is_file:
                    break
                continue
            assert frame is not None
            yield frame

    @property
    def is_file(self) -> bool:
        return self._is_file

    @property
    def position_seconds(self) -> float:
        return self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 if self._cap else 0.0

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def frame_width(self) -> int:
        if self._cap is None:
            return self.width
        return int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    @property
    def frame_height(self) -> int:
        if self._cap is None:
            return self.height
        return int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "CameraSource":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"CameraSource(source={self.source!r}, "
            f"{'open' if self.is_open else 'closed'})"
        )
