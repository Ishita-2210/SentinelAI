"""Local presentation launcher. No serial discovery, downloads or firmware uploads."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare(source="0", *, no_vlm=False, no_llm=False, max_seconds=0, no_loop=False):
    from backend.config.settings import Settings, _apply_yaml
    config_path = ROOT / "config.presentation.yaml"
    cfg = Settings(project_root=ROOT)
    _apply_yaml(cfg, config_path)
    if cfg.esp32.enabled:
        raise ValueError("Presentation config must disable ESP32; refusing serial/network hardware access")
    if cfg.api.host != "127.0.0.1":
        raise ValueError("Presentation API must bind to127.0.0.1")
    if not (cfg.vlm.enabled and cfg.llm.enabled):
        raise ValueError("Presentation config must enable both AI models; use explicit opt-outs")
    if max_seconds < 0:
        raise ValueError("MaxSeconds must be nonnegative")
    if str(source).casefold() == "esp32":
        from backend.camera.hardware_gate import load_approval, require_diagnostics
        approval = load_approval(ROOT)
        require_diagnostics(ROOT, approval)
        selected, kind = "esp32", "esp32_camera_uart"
    elif str(source).startswith(("http://", "https://")):
        from urllib.parse import urlsplit
        if not urlsplit(source).hostname:raise ValueError("MJPEG URL requires a host")
        selected, kind = str(source), "network_mjpeg"
    elif str(source).isdigit():
        selected = str(int(source))
        kind = "webcam"
    else:
        selected_path = cfg.resolve_path(source)
        if not selected_path.is_file():
            raise ValueError("Video file not found: " + str(selected_path))
        import cv2
        cap = cv2.VideoCapture(str(selected_path))
        try:
            if not cap.isOpened() or not cap.read()[0]:
                raise ValueError("Video has no decodable first frame: " + str(selected_path))
        finally:
            cap.release()
        selected = str(selected_path)
        kind = "recorded_video"
    if not cfg.resolve_path(cfg.detector.model_path).is_file():
        raise ValueError("Detector weights missing: " + cfg.detector.model_path)
    warnings = []
    from huggingface_hub import try_to_load_from_cache
    for name, model_id, disabled in (("VLM",cfg.vlm.base_model_id,no_vlm),("LLM",cfg.llm.model_id,no_llm)):
        if not disabled and not isinstance(try_to_load_from_cache(model_id,"config.json"),str):
            warnings.append(name + " cache missing; worker will report model loading error. See DEMO_GUIDE.md")
    if not no_vlm and cfg.vlm.runtime_path and not (cfg.resolve_path(cfg.vlm.runtime_path)/"transformers/__init__.py").is_file():
        warnings.append("Florence compatibility runtime missing: " + cfg.vlm.runtime_path)
    command = [sys.executable,"-B","-u","-m","backend.main","--config",str(config_path),
               "--source",selected,"--no-display","--no-vlm" if no_vlm else "--vlm",
               "--no-llm" if no_llm else "--llm"]
    if kind == "recorded_video" and not no_loop:
        command.append("--loop")
    if max_seconds:
        command.extend(["--max-seconds",str(max_seconds)])
    return dict(command=command,source=selected,source_kind=kind,serial_enabled=(kind=="esp32_camera_uart"),
                dashboard_url="http://127.0.0.1:"+str(cfg.api.port),warnings=warnings)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",default="0")
    parser.add_argument("--no-vlm",action="store_true")
    parser.add_argument("--no-llm",action="store_true")
    parser.add_argument("--no-loop",action="store_true")
    parser.add_argument("--max-seconds",type=float,default=0)
    parser.add_argument("--check",action="store_true",help="Validate without starting the application")
    args=parser.parse_args(argv)
    try:
        info=prepare(args.source,no_vlm=args.no_vlm,no_llm=args.no_llm,
                     max_seconds=args.max_seconds,no_loop=args.no_loop)
    except (ValueError,ImportError,OSError) as exc:
        # Expected validation failures use stdout so Windows PowerShell does not
        # wrap native stderr as NativeCommandError under ErrorActionPreference=Stop.
        print("Presentation preflight failed: "+str(exc),flush=True)
        print("Application not started; no application log was created.",flush=True)
        if str(args.source).casefold() == "esp32":
            print("ESP32 camera remains blocked; no other video source was opened.",flush=True)
            print("The overheating concern requires electrical inspection before any hardware session.",flush=True)
        return 2
    if args.check:
        print(json.dumps(info,indent=2))
        return 0
    import socket
    port=int(info["dashboard_url"].rsplit(":",1)[1])
    with socket.socket() as sock:
        sock.settimeout(.5)
        if sock.connect_ex(("127.0.0.1",port))==0:
            print("Port already in use: "+info["dashboard_url"]+". Stop the existing server first.",file=sys.stderr)
            return 2
    log_dir=ROOT/"data/logs"
    log_dir.mkdir(parents=True,exist_ok=True)
    log_path=log_dir/("presentation_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f")+".log")
    info["log_path"]=str(log_path)
    (log_dir/"presentation_latest.json").write_text(json.dumps(info,indent=2))
    print("Dashboard: "+info["dashboard_url"],flush=True)
    print("Log: "+str(log_path),flush=True)
    print("Source: "+info["source_kind"]+" "+info["source"]+("; verified camera stream port selected" if info["serial_enabled"] else "; ESP32 serial disabled"),flush=True)
    print("Florence/LLM start asynchronously; inspect their status and completed-inference counters.",flush=True)
    for warning in info["warnings"]:print("WARNING: "+warning,flush=True)
    import os
    env=os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8",SENTINEL_CONFIG=str(ROOT/"config.presentation.yaml"),
               OMP_NUM_THREADS="2",MKL_NUM_THREADS="2",TOKENIZERS_PARALLELISM="false")
    with log_path.open("w",encoding="utf-8") as log:
        # Guard independently of configuration: this launcher never permits serial opening.
        guard="import serial,runpy; serial.Serial=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Physical serial is disabled by presentation launcher')); runpy.run_module('backend.main',run_name='__main__')"
        if info["source_kind"] == "esp32_camera_uart":
            # Explicit source selection plus independently verified gates permits
            # only the receive-only camera source. Backend telemetry stays off.
            guard="import runpy; runpy.run_module('backend.main',run_name='__main__')"
        child_command=info["command"][:3]+["-c",guard]+info["command"][5:]
        # Replace `-m backend.main`; retain the exact validated application flags.
        proc=subprocess.Popen(child_command,cwd=ROOT,env=env,stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace")
        try:
            for line in proc.stdout:
                log.write(line);log.flush()
                print(line,end="",flush=True)
            return proc.wait()
        except KeyboardInterrupt:
            # Console Ctrl+C also reaches the application; allow its cleanup to finish.
            try:return proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.terminate()
                return proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.terminate();proc.wait(timeout=10)
            proc.stdout.close()


if __name__=="__main__":raise SystemExit(main())
