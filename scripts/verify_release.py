"""Opt-in real-video/model/API/browser verification. Never opens serial or a webcam.

All reports, images, events and SQLite files stay in a new ignored data directory.
The input must be an existing local video the operator is authorized to process.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]


def wait_until(check, timeout, process):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Application exited early ({process.returncode}); see application.log")
        value = check()
        if value:
            return value
        time.sleep(.25)
    raise TimeoutError("Verification stage timed out")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='Authorized existing local video, never a device or URL')
    parser.add_argument('--base', action='store_true', help='Explicitly verify Florence base-caption mode without a local adapter')
    args = parser.parse_args(argv)
    source = args.source.resolve()
    if not source.is_file():
        parser.error('Source must be an existing local video file')
    out = ROOT / 'data' / ('release_validation_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(parents=True)
    cfg = yaml.safe_load((ROOT / 'config.presentation.yaml').read_text(encoding='utf-8'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    cfg.update(api={'host':'127.0.0.1','port':port}, esp32={'enabled':False},
               database={'path':str(out / 'events.db')}, evidence={'output_dir':str(out / 'events')})
    if args.base:
        cfg['vlm']['adapter_dir'] = None
    # Exercise a manual saved-evidence request deterministically after loading;
    # avoid filling the automatic queue while repeated-video models warm up.
    cfg['vlm']['event_types'] = []
    config = out / 'config.yaml'
    config.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    report = {'source_scope':'explicit local video; not physical ESP32 verification', 'physical_hardware_tested':False}
    stop_file = out / 'stop.request'
    guard = f'''import serial,runpy,threading,time,_thread
from pathlib import Path
serial.Serial=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Physical serial forbidden in release verification'))
def stop_when_requested():
    while not Path({str(stop_file)!r}).exists():
        time.sleep(.1)
    _thread.interrupt_main()
threading.Thread(target=stop_when_requested,daemon=True).start()
runpy.run_module('backend.main',run_name='__main__')
'''
    command = [sys.executable,'-B','-u','-c',guard,'--config',str(config),'--source',str(source),
               '--loop','--no-display','--vlm','--llm','--max-seconds','360']
    with (out / 'application.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        client = httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=5,trust_env=False)
        try:
            def ready():
                try:
                    h = client.get('/api/health').json()
                except (httpx.HTTPError, ValueError):
                    return None
                for model in h.get('models',{}).values():
                    if model['state'] == 'error': raise RuntimeError(model.get('error'))
                return h if h.get('frames_arriving') and all(m['state'] == 'ready' for m in h.get('models',{}).values()) else None
            health = wait_until(ready,195,process)
            assert health['source_kind'] == 'video_file' and health['esp32_camera_verified'] is False
            report['initial_health'] = health
            print('Real video preview and both local models ready.',flush=True)
            def find_event():
                return next((e for e in client.get('/api/events').json()['events'] if e.get('evidence_path')),None)
            event = wait_until(find_event,20,process)
            response = client.post(f"/api/events/{event['id']}/verify")
            response.raise_for_status()
            def checked():
                e = client.get(f"/api/events/{event['id']}").json()
                if e.get('vlm_status') == 'error': raise RuntimeError(e.get('vlm_error'))
                return e if e.get('vlm_status') == 'inconclusive' and e.get('vlm_raw_text') else None
            report['vlm_event'] = wait_until(checked,75,process)
            assert report['vlm_event']['vlm_duration_ms'] >= 0
            print('Genuine Florence inference completed; result remains inconclusive.',flush=True)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge',headless=True)
                try:
                    page = browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='reduce')
                    errors = []
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(str(client.base_url),wait_until='domcontentloaded')
                    page.wait_for_function("!document.getElementById('live-preview').hidden && document.getElementById('live-preview').naturalWidth > 0",timeout=20000)
                    page.locator('.inspect-event').first.click()
                    page.wait_for_selector('#detail-image')
                    page.wait_for_function("document.getElementById('detail-image').naturalWidth > 0",timeout=10000)
                    page.wait_for_selector('#detail-ask')
                    page.click('#detail-ask')
                    assert page.input_value('#qa-question').startswith('Show event #')
                    frames_before = client.get('/api/health').json()['frames_processed']
                    with page.expect_response(lambda r:'/api/llm/query' in r.url,timeout=65000) as response_info:
                        page.click('#qa-submit')
                    answer = response_info.value.json()
                    assert answer['llm_used'] and answer['generation_status'] == 'validated',answer
                    assert answer['inference_ms'] >= 0
                    page.wait_for_function("document.getElementById('qa-answer').textContent.length > 0")
                    assert page.locator('#qa-sources .inspect-event').count() > 0
                    report['llm_answer'] = answer
                    assert client.get('/api/health').json()['frames_processed'] > frames_before
                    page.screenshot(path=str(out / 'dashboard_desktop.png'),full_page=True)
                    page.locator('#qa-sources .inspect-event').first.click()
                    page.wait_for_selector('#detail-image')
                    page.screenshot(path=str(out / 'event_detail.png'))
                    page.keyboard.press('Escape')
                    assert not page.locator('#event-dialog').evaluate('(d) => d.open')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(out / 'dashboard_mobile.png'),full_page=True)
                    report['browser'] = {'desktop':True,'mobile':True,'event_detail':True,'escape_closes_dialog':True,'source_links':True,'errors':errors}
                    assert not errors,errors

                    # Separate, explicitly simulated adverse-state UI checks.
                    # These fixtures do not contribute to real-model/hardware claims.
                    injected = dict(event, description='<img src=x onerror="window.__unsafe=1">',
                                    event_type='<script>window.__unsafe=1</script>',
                                    class_name='" onmouseover="window.__unsafe=1',
                                    evidence_path='missing\'"<keyframe>.jpg',vlm_error='simulated model unavailable')
                    page.route('**/api/events?*',lambda route:route.fulfill(json={'events':[injected],'count':1}))
                    page.route(f"**/api/events/{event['id']}",lambda route:route.fulfill(json=injected))
                    page.route('**/evidence/**',lambda route:route.fulfill(status=404,body='simulated missing evidence'))
                    page.wait_for_function("document.getElementById('event-list').textContent.includes('window.__unsafe')",timeout=10000)
                    assert page.evaluate('window.__unsafe === undefined')
                    page.locator('#event-list .inspect-event').first.click()
                    page.wait_for_function("document.getElementById('image-status')?.textContent.includes('unavailable')",timeout=10000)
                    assert page.evaluate('window.__unsafe === undefined')
                    page.keyboard.press('Escape')
                    page.route('**/api/health',lambda route:route.abort())
                    page.wait_for_function("document.getElementById('api-state').textContent === 'Unavailable'",timeout=10000)
                    report['simulated_ui_checks'] = {'untrusted_text_escaped':True,'missing_evidence':True,'api_unavailable':True}
                finally:
                    browser.close()
            report['final_health'] = client.get('/api/health').json()
            report['status'] = 'passed'
        except Exception as exc:
            report.update(status='failed',error=str(exc))
        finally:
            if process.poll() is None:
                # The verification-only watcher invokes Python's SIGINT handler,
                # allowing main's normal camera/model/database shutdown on Windows.
                stop_file.touch()
                try: process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    process.terminate(); process.wait(timeout=10)
                    report.update(status='failed',shutdown_error='Bounded application did not stop on time')
            report['application_exit_code'] = process.returncode
            if process.returncode != 0: report['status'] = 'failed'
            client.close()
            (out / 'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'error':report.get('error'),'report':str(out / 'report.json'),
                      'exit_code':process.returncode,'physical_hardware_tested':False},indent=2),flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
