from ultralytics import YOLO

from schemas.detection import Detection


class Detector:

    def __init__(self, model_path="yolo11n.pt"):

        self.model = YOLO(model_path)

    def detect(self, frame):

        results = self.model(frame)

        detections = []

        for box in results[0].boxes:

            cls = int(box.cls[0])

            conf = float(box.conf[0])

            x1, y1, x2, y2 = box.xyxy[0].tolist()

            detections.append(

                Detection(

                    class_id=cls,

                    class_name=self.model.names[cls],

                    confidence=conf,

                    x1=x1,

                    y1=y1,

                    x2=x2,

                    y2=y2

                )

            )

        return detections