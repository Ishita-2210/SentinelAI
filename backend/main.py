import cv2

from detector.detector import Detector

detector = Detector()

cap = cv2.VideoCapture(0)

while True:

    ret, frame = cap.read()

    if not ret:

        break

    detections = detector.detect(frame)

    for detection in detections:

        print(detection)

    cv2.imshow("SentinelAI", frame)

    if cv2.waitKey(1) == ord('q'):

        break

cap.release()

cv2.destroyAllWindows()