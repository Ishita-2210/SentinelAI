"""Camera source: local webcam or ESP32-CAM network stream."""

import time

import cv2


def parse_source(source: str | int):
    """'0' -> webcam index 0; anything else is treated as a stream URL."""

    if isinstance(source, int):
        return source

    text = str(source).strip()

    return int(text) if text.isdigit() else text


class Camera:

    def __init__(
        self,
        source: str | int = "0",
        reconnect_attempts: int = 5,
        reconnect_delay: float = 2.0,
    ):
        self.source = parse_source(source)
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.capture = None

    @property
    def is_network(self) -> bool:
        return isinstance(self.source, str)

    def open(self):

        self.capture = cv2.VideoCapture(self.source)

        if not self.capture.isOpened():
            raise RuntimeError(f"Could not open camera source: {self.source}")

    def read(self):
        """Return (success, frame). Network streams reconnect on failure."""

        if self.capture is None:
            self.open()

        success, frame = self.capture.read()

        if success or not self.is_network:
            return success, frame

        for _ in range(self.reconnect_attempts):
            time.sleep(self.reconnect_delay)

            self.capture.release()
            self.capture = cv2.VideoCapture(self.source)

            if self.capture.isOpened():
                success, frame = self.capture.read()

                if success:
                    return success, frame

        return False, None

    def release(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
