"""Check actual host capture independently; never silently choose a fallback."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.camera.camera import CameraSource,CameraError
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--source",required=True);args=ap.parse_args()
    source=int(args.source) if args.source.isdigit() else args.source
    if isinstance(source,str) and not source.startswith(("http://","https://","rtsp://")):
        source=str((ROOT/source).resolve())
    camera=CameraSource(source=source,max_failures=2,reconnect_delay_s=.2)
    report={"source":str(source),"esp32_identity_verified":False}
    try:
        with camera:
            for _ in range(4):
                ok,frame=camera.read_frame()
                if ok:
                    report.update(status="frame_received",width=frame.shape[1],height=frame.shape[0],channels=frame.shape[2])
                    print(json.dumps(report));return 0
        report["status"]="no_frame"
    except CameraError as exc:report.update(status="error",error=str(exc))
    print(json.dumps(report));return 1
if __name__=="__main__":sys.exit(main())
