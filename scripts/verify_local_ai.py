"""Full local-AI/perception/browser integration. Explicit real weights and COM9."""
import concurrent.futures
import json,os,subprocess,sys,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
BASE="http://127.0.0.1:8004"
def main():
    out=ROOT/"data/integration";out.mkdir(parents=True,exist_ok=True)
    report={"source_kind":"repeated real photo integration fixture; not ESP32 camera"}
    env=os.environ.copy();env["SENTINEL_CONFIG"]=str(out/"config.yaml");env["PYTHONIOENCODING"]="utf-8"
    with (out/"application.log").open("w",encoding="utf-8") as log:
        proc=subprocess.Popen([sys.executable,"-B","-u","-m","backend.main","--vlm","--llm",
            "--source","data/demo/still_image_fixture.avi","--loop","--no-display",
            "--max-seconds","90"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        client=httpx.Client(base_url=BASE,timeout=5,trust_env=False)
        try:
            start=time.monotonic();last_states=None;history=[]
            while time.monotonic()-start<215:
                if proc.poll() is not None:raise RuntimeError("Pipeline exited; see application.log")
                try:
                    health=client.get("/api/health").json()
                    states={k:v["state"] for k,v in health["models"].items()}
                    if states!=last_states:
                        print(states,"frames",health.get("frames_processed"),flush=True)
                        history.append(dict(elapsed=time.monotonic()-start,states=states,frames=health.get("frames_processed",0)))
                        last_states=states
                    if any(x=="error" for x in states.values()):raise RuntimeError(str(health["models"]))
                    if all(x=="ready" for x in states.values()) and health.get("frames_processed",0)>5:break
                except (httpx.HTTPError,KeyError,ValueError):pass
                time.sleep(.5)
            assert all(x=="ready" for x in states.values()),health
            report["state_history"]=history;report["health"]=health
            assert health["source_kind"]=="video_file" and health["esp32_camera_verified"] is False
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if client.get("/api/events?event_type=LOITERING").json()["count"]:
                    break
                time.sleep(.3)
            events=client.get("/api/events?limit=20").json()["events"]
            assert events
            ev=events[0]
            response=client.post("/api/events/"+str(ev["id"])+"/verify")
            assert response.status_code==202,response.text
            frames_before=health["frames_processed"]
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(lambda:client.post("/api/llm/query",
                    json={"question":"When was the latest loitering event?","limit":5},timeout=60))
                durations=[]
                while not future.done():
                    t=time.monotonic();poll=client.get("/api/health");durations.append(time.monotonic()-t)
                    assert poll.status_code==200
                    time.sleep(.1)
                answer=future.result().json()
            report["qa"]=answer;report["health_response_seconds_during_qa"]=durations
            assert answer["llm_used"] and answer["generation_status"]=="validated",answer
            assert answer["source_event_ids"],answer
            time.sleep(2)
            report["frames_after_qa"]=client.get("/api/health").json()["frames_processed"]
            assert report["frames_after_qa"]>frames_before
            deadline=time.monotonic()+65
            while time.monotonic()<deadline:
                checked=client.get("/api/events/"+str(ev["id"])).json()
                if checked.get("vlm_status") in {"inconclusive","error"}:break
                time.sleep(.3)
            report["vlm_event"]=checked
            assert checked["vlm_status"]=="inconclusive" and checked["vlm_raw_text"],checked
            from playwright.sync_api import sync_playwright
            errors=[]
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="msedge",headless=True)
                page=browser.new_page(viewport={"width":1500,"height":1100})
                page.on("pageerror",lambda exc:errors.append(str(exc)))
                page.goto(BASE,wait_until="domcontentloaded")
                page.wait_for_function("document.getElementById('pill-llm').textContent.includes('ready')",timeout=15000)
                page.wait_for_function("document.getElementById('live-preview').naturalWidth>0",timeout=15000)
                page.fill("#qa-question","Which events have VLM verification results?")
                with page.expect_response(lambda response:"/llm/query" in response.url,timeout=60000) as response_info:
                    page.click("#qa-submit")
                ui_answer=response_info.value.json()
                page.wait_for_function("document.getElementById('qa-answer').textContent.length>0",timeout=10000)
                assert ui_answer["llm_used"] and ui_answer["generation_status"]=="validated",ui_answer
                assert page.locator("#qa-sources li").count()>0
                report["dashboard_qa"]=ui_answer
                report["dashboard_errors"]=errors
                report["dashboard_model_text"]=page.locator("#llm-detail").inner_text()
                page.screenshot(path=str(out/"dashboard_local_ai.png"),full_page=True)
                assert not errors,errors
                browser.close()
            proc.wait(timeout=260)
            assert proc.returncode==0,proc.returncode
            report["status"]="passed"
        except Exception as exc:
            report.update(status="failed",error=str(exc))
            if proc.poll() is None:
                try:proc.wait(timeout=260)
                except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=10)
        finally:
            client.close()
            (out/"end_to_end.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return 0 if report.get("status")=="passed" else 1
if __name__=="__main__":sys.exit(main())
