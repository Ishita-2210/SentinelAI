# Demonstration guide - Windows PowerShell

The normal presentation launcher enables both local models, disables ESP32 serial, validates its video/configuration, and logs to `data/logs/presentation_*.log`. Florence and SmolLM2 run in local managed Python workers, not Ollama. No inference server or cloud credentials are needed. The dashboard is http://127.0.0.1:8010.

```powershell
Set-Location D:\SentinelAI
& .\scripts\run_presentation.ps1
# Alternatively, use the laptop webcam:
& .\scripts\run_presentation.ps1 -Source 0
```

Run one command at a time. The default is the recorded laptop video `data/demo/webcam.avi`, looped and explicitly labelled `video_file`; source0 selects the actual webcam. Ctrl+C stops the foreground launcher. Actual preview frames refresh separately from event evidence. The preview hides stale/unavailable images and distinguishes a connected WebSocket from arriving frames. Model pills show loading/error/ready, error messages and completed-inference counters; ready alone means weights loaded, not inference validated. The event list shows genuine Florence outputs and the QA form performs genuine local LLM inference when ready. The small LLM selects retrieved source IDs; factual prose comes from SQLite. Florence's presence output remains uncalibrated/inconclusive for temporal event verification.

Preflight and an explicitly reduced mode are available:
```powershell
& .\scripts\run_presentation.ps1 -Check
# Explicit opt-out only, if needed:
& .\scripts\run_presentation.ps1 -NoVLM -NoLLM
# Bounded run using the same default models and safe configuration:
& .\scripts\run_presentation.ps1 -MaxSeconds 240
```

No ESP32-origin image, ROM synchronization, camera PING/PONG or sensor PID has been physically verified. Neither the default launcher nor its validation opens COM9. See ESP32_SETUP.md for the unchanged electrical gates.

## Preflight
```powershell
Set-Location D:\SentinelAI
& .\.venv\Scripts\Activate.ps1
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m compileall -q backend
& .\.venv\Scripts\python.exe -m pytest -q tests
& .\.venv\Scripts\python.exe -m backend.main --help
# Do not power/connect the wired DevKit until camera-board supply and UART checks are resolved.
```
If activation is blocked, continue using the explicit .venv Python path. The serial check must run while the backend and Serial Monitor are stopped.

For missing core libraries:
```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-core.txt
```

## Primary live demonstration
Use the laptop webcam for this verified demonstration. Keep the wired camera/DevKit assembly unpowered until the checks in ESP32_SETUP.md pass. The pipeline continues with ESP32 disconnected. Its prior COM9 USB tests are historical, not current camera verification.
```powershell
& .\.venv\Scripts\python.exe -m backend.main --config config.presentation.yaml --source 0 --vlm --llm --max-seconds 120
```
Open http://127.0.0.1:8010 in a browser. Show camera, YOLO and ESP32 status, enter the configured zone and remain for 10 seconds. Open the resulting evidence thumbnail and inspect track ID, timestamp and deterministic event label. Wait for actual VLM/LLM ready states; check the saved-keyframe presence hypothesis and ask "When was the latest loitering event?". Model output remains inconclusive for temporal verification. For core-only operation use --no-vlm --no-llm.

Default entrance zone is x=0..1000, y=0..1000 in source pixels. Adjust named zones to actual camera dimensions in config.yaml before the presentation.

## Bounded real-video replay
data/demo/webcam.avi is an actual 30-frame, 640x480 webcam recording captured during verification.
```powershell
& .\.venv\Scripts\python.exe -m backend.main --source data/demo/webcam.avi --config data/demo/webcam_demo.yaml --no-vlm --no-display --max-frames 30 --trace data/evaluation/webcam_frames.jsonl
```
It contains approximately 3 seconds at 10 FPS: expect entry; it is too short for a 10-second loitering event. Processing time can exceed video duration. --loop restarts a new temporal segment on each rewind, so dwell must never accumulate across replay boundaries.

For a longer controlled demonstration:
```powershell
& .\.venv\Scripts\python.exe scripts/prepare_demo.py
& .\.venv\Scripts\python.exe -m backend.main --source data/demo/still_image_fixture.avi --config data/demo/config.yaml --no-vlm --no-display --loop --max-seconds 90
```
Open http://localhost:8000 while this runs. This fixture repeats a real photo for 12 seconds; YOLO detections and storage are real, but movement and field accuracy are not evaluated. An entry and a 10-second dwell event should be visible. Explain this limitation aloud.

## Browser and persistence check
Microsoft Edge and requirements-verification.txt are needed.
```powershell
# --require-esp32 is a future physical check: do not run it in the present unverified assembly.
& .\.venv\Scripts\python.exe scripts/verify_demo.py --source data/demo/webcam.avi --config data/demo/webcam_demo.yaml --output data/evaluation/webcam_demo
```
These bounded checks start the pipeline, inspect REST/WebSocket/evidence/UI, save screenshots, then launch a fresh API on port 8001 to verify persistence. Stop other servers first.

## Review history after detection stops
For the photo fixture's database:
```powershell
$env:SENTINEL_CONFIG = 'D:\SentinelAI\data\demo\config.yaml'
& .\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```
In another PowerShell window:
```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/events
Invoke-RestMethod http://localhost:8000/api/stats
Invoke-RestMethod http://localhost:8000/api/event_types
Get-ChildItem D:\SentinelAI\data\demo\events
```
API-only mode provides saved history; it does not start detection or report a live camera. Open http://localhost:8000/docs for endpoint schemas. Ctrl+C stops this server. Clear a temporary configuration override before returning to defaults:
```powershell
Remove-Item Env:SENTINEL_CONFIG -ErrorAction SilentlyContinue
```

## Recovery
- Webcam unavailable: close other camera applications, try --source 1, or replay the verified clip.
- ESP32 disconnected: vision continues; dashboard reports device failure. With the newly reported wiring, keep both boards unpowered until board-specific supply verification; do not reconnect USB solely to clear a status.
- Corrupt/unavailable network input: connection/read timeouts and bounded reconnect apply. The WROOM board itself does not supply a camera stream.
- Missing weights: restore the existing yolo11n.pt at the repository root or configure its absolute path. Startup reports a model error rather than downloading silently.
- Port 8000 occupied: stop the old server or set api.port in YAML; use that same port in the browser.
- VLM unavailable: inspect data/logs/vlm-worker.log and the dashboard error; use launcher -NoVLM only as an explicit opt-out. Do not silently disable it.
- Stop main with Q/Escape or Ctrl+C; bounded demos stop automatically and close SQLite and capture resources.

data/demo and data/evaluation contain actual verification records. Keep them for submission; repeated runs append events to their respective databases.

## Real local-model verification
See LOCAL_MODELS_SETUP.md for dependencies and explicit cache setup. With existing weights cached:
```powershell
& .\.venv\Scripts\python.exe scripts/verify_local_ai.py
```
This bounded integration test uses the labelled photo fixture, starts both local models, checks SQL QA and saved-keyframe VLM results, and opens Edge to verify dashboard sources. It does not test the camera-board UART path.


## Local model recovery commands (only if files are missing)

These downloads/installations were not needed for the verified cache. Do not run them merely because loading is in progress. They require network access and write into the model cache/Florence overlay.

```powershell
& .\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('microsoft/Florence-2-base-ft'); snapshot_download('HuggingFaceTB/SmolLM2-135M-Instruct')"
& .\.venv\Scripts\python.exe -m pip install --target data/evaluation/vlm_runtime --no-deps -r requirements-vlm-compat.txt
```

The experimental adapter is preserved at `backend/vlm/models/sentinel-vqa-v1/best`; if unavailable the worker reports its base-model fallback warning. No adapter download is invented. The overlay isolates Florence's compatible Transformers4.49/PEFT0.14 from the main environment. Inspect `data/logs/presentation_latest.json` for the exact command/log path and `data/logs/{vlm,llm}-worker.log` for dependency/loading details. Failures/timeouts surface in API models, dashboard and event verification records.

For the full real-inference/browser check, start the launcher with `-MaxSeconds 240` in one terminal, then run in another:

```powershell
& .\.venv\Scripts\python.exe scripts/verify_presentation.py
```

This attaches to port8010; it does not start a second backend or open serial. It checks changing JPEG bytes/sequence, a real Florence event result, browser-submitted local LLM generation, continued video processing during QA, WebSocket delivery and browser-only preview failure/recovery. The deliberate404 preview outage is a test, not a real camera failure. Results: `data/presentation/real_ai_validation.json` and `dashboard_ai_enabled.png`. Ordinary regression tests remain simulations.
