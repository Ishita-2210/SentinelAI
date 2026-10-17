"""SentinelAI real-time pipeline.

    Camera -> YOLO11n -> ByteTrack -> State Manager -> Event Engine
        -> SQLite + keyframe evidence
        -> (background) Florence-2 verification -> alerts / ESP32
        -> live feed for the dashboard

Run:
    python -m backend.main               # window + pipeline
    python -m backend.main --headless    # no window (servers, dashboard only)

The dashboard/API is a separate process: python -m backend.api.app
"""

import argparse
import time
from datetime import datetime

import cv2

from backend.camera.camera import Camera
from backend.config.settings import get_settings
from backend.database.event_database import EventDatabase
from backend.detector.detector import Detector
from backend.event_engine.event_engine import EventEngine
from backend.evidence.keyframe_capture import KeyframeCapture
from backend.services.alert_service import AlertService
from backend.services.live_feed import LiveFeed
from backend.services.verification_worker import (
    VerificationJob,
    VerificationWorker,
)
from backend.state_manager.state_manager import StateManager
from backend.tracker.tracker import Tracker
from backend.vlm.vlm import VisualVerifier

# Events that get a visual check by the VLM and may raise an alert.
VERIFIED_EVENT_TYPES = {"UNATTENDED_OBJECT", "LOITERING", "RUNNING"}


def draw_tracks(frame, tracks, states):
    """Draw boxes and labels, colour-coded by state."""

    for track in tracks:

        box = track.bounding_box

        x1 = int(box.x1)
        y1 = int(box.y1)
        x2 = int(box.x2)
        y2 = int(box.y2)

        state = next(
            (s for s in states if s.track_id == track.track_id),
            None,
        )

        box_color = (0, 255, 0)
        label = f"{track.class_name} ID:{track.track_id}"

        if state is not None and state.unattended:
            box_color = (0, 0, 255)
            label = f"UNATTENDED | {label}"

        elif state is not None and state.loitering:
            box_color = (0, 0, 255)
            label = f"LOITERING | {label}"

        elif state is not None and state.running:
            box_color = (255, 0, 0)
            label = f"RUNNING | {label}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

        cv2.putText(
            frame,
            label,
            (x1, max(y1 - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            box_color,
            2,
        )


def main():

    parser = argparse.ArgumentParser(description="SentinelAI pipeline")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="do not open a preview window",
    )
    args = parser.parse_args()

    settings = get_settings()

    # ----------------------------------
    # Initialize components
    # ----------------------------------

    detector = Detector()
    tracker = Tracker()
    state_manager = StateManager()
    event_engine = EventEngine()
    database = EventDatabase(settings.database_path)
    evidence = KeyframeCapture(settings.evidence_dir)
    live_feed = LiveFeed()

    verifier = VisualVerifier(
        model_id=settings.vlm_model_id,
        adapter_path=settings.vlm_adapter_path,
        enabled=settings.vlm_enabled,
    )

    alerts = AlertService(
        esp32_url=settings.esp32_url,
        event_types=settings.alert_event_types,
        cooldown_sec=settings.alert_cooldown_sec,
    )

    worker = VerificationWorker(
        settings.database_path,
        verifier,
        alerts,
    )
    worker.start()

    camera = Camera(settings.camera_source)
    camera.open()

    print(
        f"SentinelAI running | camera={settings.camera_source} | "
        f"vlm={'on' if settings.vlm_enabled else 'off'} | "
        f"alerts={'ESP32' if not alerts.dry_run else 'dry-run'}"
    )

    frame_count = 0
    started = time.monotonic()

    # ----------------------------------
    # Main loop
    # ----------------------------------

    try:
        while True:

            success, frame = camera.read()

            if not success:
                print("Failed to read frame.")
                break

            frame_count += 1

            detections = detector.detect(frame)
            tracks = tracker.update(detections)

            timestamp = datetime.now()

            states = state_manager.update(tracks, timestamp)
            events = event_engine.update(states, timestamp)

            # ----------------------------------
            # Persist events + evidence
            # ----------------------------------

            for event in events:

                # Frame is still clean here: boxes are drawn afterwards.
                evidence_path = evidence.save(
                    frame,
                    event.event_type,
                    event.track_id,
                    event.timestamp,
                )

                event_id = database.save_event(event, evidence_path)

                print(
                    f"EVENT: {event.event_type} | "
                    f"ID: {event.track_id} | "
                    f"Zone: {event.zone} | "
                    f"{event.description}"
                )

                if event.event_type in VERIFIED_EVENT_TYPES:
                    worker.submit(
                        VerificationJob(
                            event_id=event_id,
                            event_type=event.event_type,
                            class_name=event.class_name,
                            evidence_path=evidence_path,
                        )
                    )

            # ----------------------------------
            # Draw + publish
            # ----------------------------------

            draw_tracks(frame, tracks, states)

            elapsed = max(time.monotonic() - started, 1e-6)

            live_feed.publish(
                frame,
                {
                    "fps": round(frame_count / elapsed, 1),
                    "tracks": len(tracks),
                    "unattended": sum(1 for s in states if s.unattended),
                    "loitering": sum(1 for s in states if s.loitering),
                    "running": sum(1 for s in states if s.running),
                },
            )

            if not args.headless:
                cv2.imshow("SentinelAI", frame)

                # Q = quit
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        pass

    finally:
        worker.stop()
        camera.release()

        if not args.headless:
            cv2.destroyAllWindows()

        database.close()


if __name__ == "__main__":
    main()
