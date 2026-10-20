"""Attach to the presentation launcher; real local models/browser, no serial."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import httpx


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url",default="http://127.0.0.1:8010")
    args=ap.parse_args()
    out=Path(__file__).resolve().parents[1]/"data/presentation"
    report={"status":"failed","source":"recorded laptop video, not ESP32 camera"}
    start=time.monotonic()
    try:
        with httpx.Client(base_url=args.url,timeout=5,trust_env=False) as client:
            history=[];last=None
            while time.monotonic()-start<120:
                try:
                    health=client.get("/api/health").json()
                    states={k:m["state"] for k,m in health["models"].items()}
                    if states!=last:
                        print(states,flush=True);history.append(states);last=states
                    if any(s=="error" for s in states.values()):raise RuntimeError(str(health["models"]))
                    if all(s=="ready" for s in states.values()) and health.get("frames_arriving"):break
                except (httpx.HTTPError,KeyError,ValueError):pass
                time.sleep(.25)
            else:raise TimeoutError("Models/video not ready; inspect launcher/worker logs")
            assert health["source_kind"]=="video_file" and not health["esp32_camera_verified"]
            report["model_history"]=history
            first=client.get("/api/frame.jpg");first.raise_for_status()
            time.sleep(.8)
            second=client.get("/api/frame.jpg");second.raise_for_status()
            assert first.headers["x-preview-sequence"]!=second.headers["x-preview-sequence"]
            assert hashlib.sha256(first.content).digest()!=hashlib.sha256(second.content).digest()
            report["changing_real_frames"]=True
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                events=client.get("/api/events?limit=50").json()["events"]
                checked=next((e for e in events if e.get("vlm_status")=="inconclusive" and e.get("vlm_raw_text")),None)
                models=client.get("/api/models").json()
                if checked and models["vlm"].get("inference_count",0)>0:break
                time.sleep(.3)
            else:raise TimeoutError("No actual Florence result; inspect VLM status and event errors")
            report["vlm_event"]=checked
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="msedge",headless=True)
                try:
                    page=browser.new_page(viewport={"width":1500,"height":1100})
                    errors=[];messages=[]
                    page.on("pageerror",lambda exc:errors.append(str(exc)))
                    page.on("websocket",lambda ws:ws.on("framereceived",lambda value:messages.append(value)))
                    page.goto(args.url,wait_until="domcontentloaded")
                    page.wait_for_function("document.getElementById('live-preview').naturalWidth>0 && document.getElementById('live-preview').style.display==='block'",timeout=15000)
                    page.wait_for_function("document.getElementById('pill-llm').textContent.includes('ready')",timeout=15000)
                    page.wait_for_selector("#event-list .ev",timeout=10000)
                    before=client.get("/api/health").json()["frames_processed"]
                    page.fill("#qa-question","When was the latest person entered event?")
                    with page.expect_response(lambda response:"/api/llm/query" in response.url,timeout=60000) as response:
                        page.click("#qa-submit")
                    answer=response.value.json()
                    assert answer["llm_used"] and answer["generation_status"]=="validated",answer
                    page.wait_for_function("document.getElementById('qa-answer').textContent.length>0",timeout=10000)
                    assert page.locator("#qa-sources li").count()>0
                    report["llm_ui_answer"]=answer
                    time.sleep(.5)
                    after=client.get("/api/health").json()["frames_processed"]
                    assert after>before
                    report["frames_during_qa"]=[before,after]
                    page.route("**/api/frame.jpg?*",lambda route:route.fulfill(status=404,body="deliberate browser-only outage test"))
                    page.wait_for_function("document.getElementById('live-preview').style.display==='none'",timeout=7000)
                    report["preview_outage_hides_old_image"]=True
                    page.unroute("**/api/frame.jpg?*")
                    page.wait_for_function("document.getElementById('live-preview').style.display==='block'",timeout=7000)
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(out/"dashboard_ai_enabled.png"),full_page=True,animations="disabled")
                    report["browser_errors"]=errors
                    report["websocket_messages"]=len(messages)
                    assert not errors and messages
                finally:browser.close()
            final=client.get("/api/health").json()
            assert all(m.get("inference_count",0)>0 for m in final["models"].values())
            report.update(status="passed",health=final,elapsed_s=time.monotonic()-start)
    except Exception as exc:
        report["error"]=str(exc)
    (out/"real_ai_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return 0 if report["status"]=="passed" else 1


if __name__=="__main__":raise SystemExit(main())
