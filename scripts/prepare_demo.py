"""Create a clearly labelled STILL-IMAGE video fixture using real dataset pixels.
This checks software integration and stationary tracking, not natural-video accuracy.
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from backend.tracker.tracker import Tracker

def main():
    out=ROOT/"data/demo"; out.mkdir(parents=True,exist_ok=True)
    tracker=Tracker(str(ROOT/"yolo11n.pt"))
    selected=None
    # Existing demonstration photos first; no generated pixels, labels or detections.
    candidates=sorted((ROOT/"dataset/images").glob("test*")) + sorted((ROOT/"dataset/images").glob("*.jpg"))
    for path in candidates[:35]:
        image=cv2.imread(str(path))
        if image is None: continue
        tracks=tracker.detect_only(image)
        print(path.name, [(x.class_name, round(x.confidence,2)) for x in tracks],flush=True)
        if any(x.class_name=="person" for x in tracks):
            selected=path; break
    if selected is None: raise RuntimeError("No person detected in candidate photos; provide representative video")
    image=cv2.imread(str(selected)); h,w=image.shape[:2]
    # MJPG avoids external codecs; 12 seconds at 10 Hz.
    target=out/"still_image_fixture.avi"
    writer=cv2.VideoWriter(str(target),cv2.VideoWriter_fourcc(*"MJPG"),10,(w,h))
    if not writer.isOpened(): raise RuntimeError("MJPG writer unavailable")
    for _ in range(120): writer.write(image)
    writer.release()
    manifest=dict(kind="repeated real still image; NOT a natural video accuracy benchmark",
                  source=str(selected),video=str(target),frames=120,fps=10,width=w,height=h)
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    (out/"config.yaml").write_text(
        "database:\n  path: data/demo/sentinelai.db\nevidence:\n  output_dir: data/demo/events\n"
        "event_engine:\n  zones:\n    - name: scene\n      x1: 0\n      y1: 0\n"
        +f"      x2: {w}\n      y2: {h}\n"
        +"vlm:\n  enabled: false\nesp32:\n  enabled: true\n  mode: serial\n")
    print(json.dumps(manifest,indent=2))
if __name__=="__main__": main()
