import cv2
from datetime import datetime

from backend.detector.detector import Detector
from backend.tracker.tracker import Tracker
from backend.state_manager.state_manager import StateManager
from backend.event_engine.event_engine import EventEngine


def main():

    detector = Detector()
    tracker = Tracker()
    state_manager = StateManager()
    event_engine = EventEngine()

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        raise RuntimeError("Could not open webcam.")

    while True:

        success, frame = camera.read()

        if not success:
            print("Failed to read frame.")
            break

        # ----------------------------------
        # Detection
        # ----------------------------------

        detections = detector.detect(frame)

        # ----------------------------------
        # Tracking
        # ----------------------------------

        tracks = tracker.update(detections)

        # ----------------------------------
        # State Management
        # ----------------------------------

        timestamp = datetime.now()

        states = state_manager.update(
            tracks,
            timestamp,
        )

        # ----------------------------------
        # Event Reasoning
        # ----------------------------------

        events = event_engine.update(
            states,
            timestamp,
        )

        # ----------------------------------
        # Print events
        # ----------------------------------

        for event in events:

            print(
                f"EVENT: {event.event_type} | "
                f"ID: {event.track_id} | "
                f"Zone: {event.zone} | "
                f"{event.description}"
            )

        # ----------------------------------
        # Draw objects
        # ----------------------------------

        for track in tracks:

            box = track.bounding_box

            x1 = int(box.x1)
            y1 = int(box.y1)
            x2 = int(box.x2)
            y2 = int(box.y2)

            state = next(
                (
                    s for s in states
                    if s.track_id == track.track_id
                ),
                None,
            )

            # Default
            box_color = (0, 255, 0)

            label = (
                f"{track.class_name} "
                f"ID:{track.track_id}"
            )

            # ----------------------------------
            # Loitering
            # ----------------------------------

            if state and state.loitering:

                box_color = (0, 0, 255)

                label = (
                    f"LOITERING | "
                    f"{track.class_name} "
                    f"ID:{track.track_id}"
                )

            # ----------------------------------
            # Running
            # ----------------------------------

            elif state and state.running:

                box_color = (255, 0, 0)

                label = (
                    f"RUNNING | "
                    f"{track.class_name} "
                    f"ID:{track.track_id}"
                )

            # ----------------------------------
            # Draw bounding box
            # ----------------------------------

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                box_color,
                2,
            )

            # ----------------------------------
            # Draw label
            # ----------------------------------

            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                box_color,
                2,
            )

        # ----------------------------------
        # Display
        # ----------------------------------

        cv2.imshow(
            "SentinelAI",
            frame,
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()