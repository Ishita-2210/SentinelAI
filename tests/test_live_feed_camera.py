import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from backend.camera.camera import Camera, parse_source
from backend.services.live_feed import LiveFeed


class LiveFeedTests(unittest.TestCase):

    def test_publish_writes_decodable_frame_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = LiveFeed(tmp, max_fps=1000)
            frame = np.full((48, 64, 3), 200, dtype=np.uint8)

            self.assertTrue(feed.publish(frame, {"fps": 12.5, "tracks": 3}))

            decoded = cv2.imdecode(
                np.frombuffer(Path(tmp, "latest.jpg").read_bytes(), np.uint8),
                cv2.IMREAD_COLOR,
            )
            self.assertEqual(decoded.shape, (48, 64, 3))

            status = json.loads(Path(tmp, "status.json").read_text())
            self.assertEqual(status["fps"], 12.5)
            self.assertEqual(status["tracks"], 3)
            self.assertIn("updated_at", status)

            # No temp files left behind by the atomic write.
            self.assertEqual(
                sorted(p.name for p in Path(tmp).iterdir()),
                ["latest.jpg", "status.json"],
            )

    def test_publish_is_throttled(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = LiveFeed(tmp, max_fps=1)
            frame = np.zeros((8, 8, 3), dtype=np.uint8)

            self.assertTrue(feed.publish(frame, {}))
            self.assertFalse(feed.publish(frame, {}))


class CameraTests(unittest.TestCase):

    def test_parse_source(self):
        self.assertEqual(parse_source("0"), 0)
        self.assertEqual(parse_source(2), 2)
        self.assertEqual(
            parse_source("http://192.168.1.50:81/stream"),
            "http://192.168.1.50:81/stream",
        )

    def test_is_network(self):
        self.assertFalse(Camera("0").is_network)
        self.assertTrue(Camera("http://x/stream").is_network)

    def test_open_missing_camera_raises_clear_error(self):
        with self.assertRaises(RuntimeError) as context:
            Camera("98").open()

        self.assertIn("Could not open camera source", str(context.exception))


if __name__ == "__main__":
    unittest.main()
