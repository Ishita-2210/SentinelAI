from ultralytics import YOLO

from backend.schemas.bounding_box import BoundingBox
from backend.schemas.detection import Detection


class Detector:

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.5,
    ):
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold

    def detect(self, frame) -> list[Detection]:

        results = self.model(
            frame,
            conf=self.confidence_threshold,
            verbose=False,
        )

        detections = []

        for box in results[0].boxes:

            class_id = int(box.cls[0])
            confidence = float(box.conf[0])

            x1, y1, x2, y2 = box.xyxy[0].tolist()

            bounding_box = BoundingBox(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
            )

            detection = Detection(
                class_id=class_id,
                class_name=self.model.names[class_id],
                confidence=confidence,
                bounding_box=bounding_box,
            )

            detections.append(detection)

        return detections