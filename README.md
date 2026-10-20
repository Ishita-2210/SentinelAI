# SentinelAI

Local video intelligence with YOLO11n, ByteTrack, event evidence, Florence-2 and source-linked local LLM answers.

SentinelAI processes a laptop webcam or a video file on a Windows laptop. It tracks objects, derives deterministic events, saves evidence in SQLite/JPEG, and serves a live dashboard through FastAPI and WebSocket. Inference runs locally; the ESP32 is a telemetry device, not the inference host.

## Features

- YOLO11n detection and persistent ByteTrack identities.
- Entry, exit, zone change, loitering, rapid-motion and unattended-object heuristics.
- Separate live annotated preview and saved event evidence/history.
- Event-triggered Florence-2 checks in a bounded asynchronous queue.
- Local SmolLM2 event QA with validated event references and factual text rendered from SQLite.
- Truthful model lifecycle/error states, preview freshness and source provenance.
- Preserved ESP32 telemetry firmware, isolated UART probes and a temporary programming bridge.

## Architecture

```text
Webcam / local video
  -> YOLO11n + ByteTrack -> state manager -> deterministic event engine
  -> JPEG evidence + SQLite -> REST / WebSocket -> browser dashboard

Saved event keyframe -> managed Florence worker -> separate visual-check metadata
Question -> retrieved SQLite records -> local SmolLM2 source selection -> linked answer

Optional, separately authorized: host alerts <-> USB ESP32 telemetry
Unverified camera path: camera ESP32 -> UART2 DevKit bridge -> USB -> host
```

See [architecture](docs/ARCHITECTURE.md) and [known limitations](docs/KNOWN_LIMITATIONS.md).

## Prerequisites

- Windows PowerShell, Git and Python 3.13 (the version used for local validation).
- A working laptop webcam, or a local video that you are authorized to use.
- Enough disk and RAM for PyTorch, YOLO and the selected local models. The tested CPU laptop had approximately 16 GB RAM; concurrent model loading can be slow.
- Microsoft Edge and Playwright only for browser verification; PlatformIO only for firmware builds.

Dependencies are pinned to the tested environment. A successful run on another machine still requires installation and model setup below. No API key, cloud inference service or Ollama server is required.

## Windows installation

From a clone of this repository:

```powershell
Set-Location <your-clone-directory>
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-local-ai.txt
& .\.venv\Scripts\python.exe -m pip check
Copy-Item config.example.yaml config.yaml
```

`config.yaml` is ignored and remains machine-local. The committed `config.example.yaml` disables ESP32 access. The normal launcher uses `config.presentation.yaml`, which enables both local models, binds to localhost and disables serial. Existing local configuration is not overwritten by repository cleanup; omit `Copy-Item` if you already have one.

## Model setup

Weights, private adapters and model caches are deliberately excluded from Git. Review each upstream model's license before using or redistributing it.

1. **YOLO11n**: the application expects `yolo11n.pt` in the repository root. An explicit first-time download through the installed Ultralytics package is:

```powershell
& .\.venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"
```

2. **Florence-2**: install the isolated compatibility overlay and explicitly download the public base model. The overlay preserves the main environment's Transformers version.

```powershell
& .\.venv\Scripts\python.exe -m pip install --target data/evaluation/vlm_runtime --no-deps -r requirements-vlm-compat.txt
& .\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('microsoft/Florence-2-base-ft')"
```

An optional local adapter can be supplied under `backend/vlm/models/sentinel-vqa-v1/best`, or set `vlm.adapter_dir: null` in `config.presentation.yaml` to select the base model explicitly. The adapter is not included or required for base-model operation. If a requested adapter is absent the worker exposes its base-model fallback warning.

3. **Local LLM**: explicitly cache `HuggingFaceTB/SmolLM2-135M-Instruct`:

```powershell
& .\.venv\Scripts\python.exe scripts/download_llm.py --download
```

After setup, model workers use offline/cache-only loading. Missing files, loading errors and inference timeouts remain visible. See [local models](docs/LOCAL_MODELS_SETUP.md) for details.

## Configure and launch

For the laptop webcam:

```powershell
& .\scripts\run_presentation.ps1 -Source 0
```

For a local video:

```powershell
& .\scripts\run_presentation.ps1 -Source 'C:\path\to\your-video.mp4'
```

Open **http://127.0.0.1:8010**. The launcher prints the log location; `data/logs/presentation_latest.json` records the latest command and log path. Ctrl+C stops the application.

Both models are enabled by default. The launcher validates the source/configuration and independently blocks serial opening. For an explicit lightweight opt-out, use `-NoVLM -NoLLM`. `-Check` validates without starting the application. Camera indices are opened only when the application starts.

### Recorded demo

The private laptop recording is not redistributed: its privacy/redistribution rights were not established for publication. Keep your own authorized clip at `data/demo/webcam.avi` to use the zero-argument launcher, or pass `-Source` as above. The default launcher fails clearly if the clip is missing; it does not fabricate frames.

Recorded-video loops reset temporal state. Repeated entries in replay history are not unique real-world arrivals. Use a webcam or an appropriately long video to demonstrate dwell naturally. Source labels distinguish video files, webcams and the unverified ESP32 camera.

### Screenshots

Screenshots are generated locally and excluded from Git because they can contain people, private video and event details. To generate your own end-to-end screenshot, first run:

```powershell
& .\scripts\run_presentation.ps1 -MaxSeconds 240
```

Then in another terminal:

```powershell
& .\.venv\Scripts\python.exe scripts/verify_presentation.py
```

This optional real-model/browser check assumes the default recorded clip is supplied locally. It saves `data/presentation/dashboard_ai_enabled.png` and `real_ai_validation.json`. Only publish screenshots you have permission to share.

## Tests and firmware builds

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
# Optional browser and firmware tooling:
& .\.venv\Scripts\python.exe -m pip install -r requirements-verification.txt
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/uart_probe
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/camera_uart_probe
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/uart_programmer_bridge
```

Firmware commands compile only; they do not upload. Ordinary tests use simulated models/serial, do not open cameras or COM9, and do not demonstrate hardware operation. The verified development run passed **173 regression tests and four firmware builds**. Separately, real local Florence/LLM inference, changing recorded-video frames, browser QA and preview recovery passed on the development laptop. These are recorded results, not a guarantee for a fresh installation; private result artifacts are not bundled.

## ESP32 status and safe setup

The original telemetry sketch is preserved under `esp32/SentinelTelemetry`. Historical physical tests established USB telemetry, ping and alert acknowledgements on the primary DevKit. No physical actuator or on-device AI is claimed.

**The ESP32 camera path does not work as a verified end-to-end integration yet.** Camera-board power/regulator routing, the second DevKit's supply/current budget, UART0/IO0/reset routing and programming controls remain unverified. Real camera PING/PONG, initialization/PID and image capture have not passed. COM9 must not be treated as a direct camera programmer.

The UART probe explicitly uses primary RX16/TX17; the camera responder and binary bridge are separate, compile-tested projects. Do not flash, erase, energize or alter wiring based on compilation. Keep real telemetry and fresh recoverable backups intact. Follow [ESP32 setup and stage gates](docs/ESP32_SETUP.md).

## Limitations and troubleshooting

- **Video missing/unreadable:** supply an authorized local file or use `-Source 0`; check permissions and codec support.
- **Camera unavailable:** close other webcam applications and check Windows camera permissions. Reconnect/error states are exposed; stale frames are hidden.
- **Port 8010 busy:** stop the existing backend before starting another launcher.
- **Models loading/error:** inspect the dashboard and `data/logs/vlm-worker.log` / `llm-worker.log`. Ready means weights loaded; completed-inference counters establish requests actually completed. Missing weights need the explicit setup commands above.
- **Florence compatibility:** install the pinned overlay; do not downgrade the main environment globally. Presence answers are uncalibrated and do not validate elapsed activity.
- **LLM scope:** the small LLM selects retrieved event IDs; it is not a general chatbot. Factual answer text comes from stored records, with a visible fallback on model failure.
- **CPU contention/queue full:** FPS varies; event checks may be skipped by the bounded queue. No throughput guarantee is claimed.
- **Accuracy:** representative detector/event/tracker field accuracy is not measured. Existing adapter evaluation did not establish an improvement. See [accuracy evaluation](docs/ACCURACY_EVALUATION.md).
- **Local-only security:** use one backend worker and the localhost presentation binding. This is not an authenticated public hosting configuration.

## Repository hygiene and licensing

Source, tests, documentation, firmware and dependency manifests are versioned. Environments, caches, secrets, local configuration, databases, logs, evidence, videos, datasets and model weights are excluded. Do not add those files with `git add -f`.

This repository preserves its existing Git history. Generated files previously committed in that history remain there; the cleaned tip stops tracking them without deleting local copies. No project redistribution license has been selected. Third-party models and dependencies retain their upstream license terms.
