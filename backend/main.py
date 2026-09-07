import cv2

from backend.detector.detector import Detector
from backend.tracker.tracker import Tracker
from datetime import datetime
from backend.state_manager.state_manager import StateManager

def main():

    detector = Detector()
    tracker = Tracker()
    state_manager = StateManager()

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        raise RuntimeError("Could not open webcam.")

    while True:

        success, frame = camera.read()

        if not success:
            print("Failed to read frame.")
            break

        # -------------------------
        # 1. Object Detection
        # -------------------------

        detections = detector.detect(frame)

        # -------------------------
        # 2. Object Tracking
        # -------------------------

        tracks = tracker.update(detections)
        timestamp = datetime.now()

        states = state_manager.update(
            tracks,
            timestamp,
        )
        
        for state in states:

            print(
                f"ID: {state.track_id} | "
                f"Object: {state.class_name} | "
                f"Position: {state.current_box.center} | "
                f"Velocity: {state.velocity}"
            )

        # -------------------------
        # 3. Visualization
        # -------------------------

        for track in tracks:

            box = track.bounding_box

            x1 = int(box.x1)
            y1 = int(box.y1)
            x2 = int(box.x2)
            y2 = int(box.y2)

            # Draw bounding box
            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2,
            )

            # Display class + track ID
            label = (
                f"{track.class_name} "
                f"ID:{track.track_id} "
                f"{track.confidence:.2f}"
            )

            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2,
            )

        cv2.imshow("SentinelAI", frame)

        # Press Q to quit
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()