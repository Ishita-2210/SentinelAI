"""Bounded real-inference, API, evidence, WebSocket and browser integration check."""
import json
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",default="data/demo/still_image_fixture.avi")
    ap.add_argument("--config",default="data/demo/config.yaml")
    ap.add_argument("--output",default="data/evaluation")
    ap.add_argument("--require-esp32",action="store_true")
    args=ap.parse_args()
    out=ROOT/args.output;out.mkdir(parents=True,exist_ok=True)
    report={"source":args.source,"config":args.config}
    errors=[]
    env=os.environ.copy();env["SENTINEL_CONFIG"]=str(ROOT/args.config)
    with (out/"demo.log").open("w",encoding="utf-8") as log:
        proc=subprocess.Popen([sys.executable,"-B","-m","backend.main","--source",
            args.source,"--loop","--no-vlm","--no-display",
            "--max-frames","300","--max-seconds","45"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+30
            while True:
                try:
                    health=httpx.get("http://127.0.0.1:8000/api/health",timeout=1)
                    if health.status_code==200 and health.json().get("frames_processed",0)>3:break
                except httpx.HTTPError:pass
                if proc.poll() is not None:raise RuntimeError("Pipeline exited before startup; see demo.log")
                if time.monotonic()>deadline:raise TimeoutError("Pipeline startup exceeded 30 seconds")
                time.sleep(.25)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="msedge",headless=True)
                page=browser.new_page(viewport={"width":1440,"height":1000})
                page.on("pageerror",lambda exc:errors.append(str(exc)))
                ws_messages=[]
                page.on("websocket",lambda ws:ws.on("framereceived",lambda payload:ws_messages.append(payload)))
                page.goto("http://127.0.0.1:8000",wait_until="domcontentloaded")
                page.wait_for_selector("#event-list .ev",timeout=20000)
                observed_width=page.wait_for_function("document.getElementById('live-preview').naturalWidth || false",timeout=15000).json_value()
                page.wait_for_timeout(1000)
                report["dashboard_event_cards"]=page.locator("#event-list .ev").count()
                report["preview_width"]=observed_width
                assert observed_width>0
                report["evidence_thumbnails"]=page.locator("#ev-grid img").count()
                report["websocket_messages"]=len(ws_messages)
                report["health"]=httpx.get("http://127.0.0.1:8000/api/health").json()
                if args.require_esp32:
                    deadline=time.monotonic()+10
                    while True:
                        h=httpx.get("http://127.0.0.1:8000/api/health").json()
                        if h.get("esp32_status")=="connected" and h.get("esp32_telemetry",{}).get("last_alert"):
                            report["esp32_host_alert_roundtrip"]=h["esp32_telemetry"]
                            break
                        if time.monotonic()>deadline:
                            raise RuntimeError("No physical ESP32 host-alert telemetry roundtrip")
                        time.sleep(.25)
                events=httpx.get("http://127.0.0.1:8000/api/events").json()["events"]
                report["events"]=events
                for ev in events:
                    assert Path(ev["evidence_path"]).is_file(),ev
                    url="http://127.0.0.1:8000/evidence/"+Path(ev["evidence_path"]).name
                    assert httpx.get(url).status_code==200,url
                    assert httpx.get("http://127.0.0.1:8000/api/events/"+str(ev["id"])).status_code==200
                assert httpx.get("http://127.0.0.1:8000/api/frame.jpg").status_code==200
                assert report["websocket_messages"]>0,"No WebSocket frames delivered"
                assert report["evidence_thumbnails"]>0
                page.screenshot(path=str(out/"dashboard.png"),full_page=True)
                report["browser_errors"]=errors
                assert not errors,errors
                browser.close()
            proc.wait(timeout=65)
            assert proc.returncode==0,proc.returncode
            # Start standalone API against the same persisted DB after pipeline shutdown.
            api=subprocess.Popen([sys.executable,"-B","-m","uvicorn","backend.api:app",
                "--host","127.0.0.1","--port","8001"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+15
                while True:
                    try:
                        res=httpx.get("http://127.0.0.1:8001/api/events",timeout=1)
                        if res.status_code==200:break
                    except httpx.HTTPError:pass
                    if time.monotonic()>deadline:raise TimeoutError("Standalone API startup")
                    time.sleep(.25)
                report["standalone_api_status"]=res.status_code
                report["persisted_event_count"]=res.json()["count"]
                assert report["persisted_event_count"]>=len(events)
            finally:
                api.terminate();api.wait(timeout=10)
            report["status"]="passed"
        except Exception as exc:
            report["status"]="failed";report["error"]=str(exc)
            if proc.poll() is None:
                try:proc.wait(timeout=55)
                except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=10)
        finally:
            (out/"demo_verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return 0 if report["status"]=="passed" else 1
if __name__=="__main__":sys.exit(main())
