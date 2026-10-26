# SentinelAI

Local video intelligence with YOLO11n, ByteTrack, event evidence, Florence-2 and source-linked local LLM answers.

SentinelAI processes a laptop webcam or a video file on a Windows laptop. It tracks objects, derives deterministic events, saves evidence in SQLite/JPEG, and serves a live dashboard through FastAPI and WebSocket. Inference runs locally; the ESP32 is a telemetry device, not the inference host.

## Why SentinelAI

Continuous video is difficult to review manually. SentinelAI turns detections into timestamped, source-linked events and saved keyframes, then lets a developer inspect what the deterministic rules and local models actually produced. It is a local-first engineering prototype; camera hardware and field accuracy have separate validation boundaries.

## Project status

| Capability | Implemented | Validation boundary |
| --- | --- | --- |
| File/webcam capture, YOLO11n, ByteTrack, event rules, SQLite/evidence | Yes | Automated contracts; recorded-video end-to-end checks. Fresh webcam behavior is machine dependent. |
| Florence-2 visual analysis | Yes | Real local inference checked separately; outputs remain uncalibrated/inconclusive. |
| SmolLM2 source-linked event QA | Yes | Real local generation and validated IDs checked separately; factual text comes from SQLite. |
| Responsive dashboard and event inspector | Yes | Browser checks include source links, keyframe inspection and unavailable/error states. |
| ESP32 telemetry | Source preserved | Historical primary-DevKit results only; no hardware tested in this release pass. |
| ESP32 camera video | Host preparation and gated firmware references | Power, programming, sensor initialization, genuine JPEG and continuous feed remain physically unverified. |

See [fresh release validation](docs/RELEASE_VALIDATION.md) for exact checks and limitations. Historical reports are dated evidence, not current guarantees.

## Features

- YOLO11n detection and persistent ByteTrack identities.
- Entry, exit, zone change, loitering, rapid-motion and unattended-object heuristics.
- Separate live annotated preview and saved event evidence/history.
- Event-triggered Florence-2 checks in a bounded asynchronous queue.
- Local SmolLM2 event QA with validated event references and factual text rendered from SQLite.
- Truthful model lifecycle/error states, preview freshness and source provenance.
- Evidence-first event inspection with original images, dimensions, hashes, actual tasks and measured processing duration.
- Written current-frame descriptions from Florence-2, followed by local LLM explanations, with saved snapshot links and optional 30-second refresh.
- Responsive, keyboard-accessible dark dashboard; bounded WebSocket delivery and local text escaping.
- Preserved ESP32 telemetry firmware, isolated UART probes and a temporary programming bridge.

## Architecture

```mermaid
flowchart TD
    W[Official: laptop webcam 0] --> C[OpenCV capture]
    V[Recorded video / reproducible fixtures] --> C
    C --> T[YOLO11n + ByteTrack]
    T --> S[State manager and deterministic event rules]
    S --> E[Unique JPEG keyframe + SQLite event ID and source metadata]
    E --> Q[Bounded event queue]
    Q --> F[Local Florence-2 worker]
    F --> R[Uncalibrated presence answer or base-model caption]
    R --> E
    E --> A[REST + WebSocket dashboard]
    U[User question] --> D[Deterministic bounded SQLite retrieval]
    E --> D
    D --> L[Local SmolLM2: constrained source selection]
    L --> A
    X[Experimental ESP32 camera: unverified] -. Physical approval and diagnostics required .-> B[UART receiver / bounded latest-frame buffer]
    B -. Separate source, never automatic fallback .-> T
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

After setup, model workers use offline/cache-only loading. Missing files, loading errors and inference timeouts remain visible. See [AI model setup and interpretation](docs/AI_MODELS.md) and [detailed local model notes](docs/LOCAL_MODELS_SETUP.md).

## Configure and launch

The official presentation source is the laptop webcam. Both Florence-2 and SmolLM2 remain enabled:

```powershell
Set-Location <your-clone-directory>
& .\scripts\run_presentation.ps1 -Source 0
```

The zero-argument launcher also selects webcam `0`. Explicit webcam selection bypasses ESP32 hardware preflight and blocks physical serial access. A failed webcam never silently changes to a video or another source.

For a local video:

```powershell
& .\scripts\run_presentation.ps1 -Source 'C:\path\to\your-video.mp4'
```

Open **http://127.0.0.1:8010**. Use **Inspect event** to trace a timeline record to its original keyframe and actual Florence output. **Ask about event** fills a supported source-ID query; answer references reopen the same inspector. The launcher prints the log location; `data/logs/presentation_latest.json` records the latest command and log path. Ctrl+C stops the application.

The **What is happening in this frame?** panel displays actual written image descriptions and scene explanations. It analyzes a saved copy of the current annotated preview; it does not describe every video frame. Automatic refresh is enabled every 30 seconds while fresh frames and a loaded VLM are available; untick it for manual use, or press **Describe current frame**. The displayed timestamp and image link identify the analyzed snapshot. Tracking rows and dynamic output panels scroll internally to keep surrounding cards in place.

Both models are enabled by default. The launcher validates the source/configuration and independently blocks serial opening. For an explicit lightweight opt-out, use `-NoVLM -NoLLM`. `-Check` validates without starting the application. Camera indices are opened only when the application starts.

### Recorded demo

The private laptop recording is not redistributed: its privacy/redistribution rights were not established for publication. Keep your own authorized clip at `data/demo/webcam.avi` and explicitly pass `-Source data/demo/webcam.avi`. The zero-argument launcher selects webcam 0. Explicit `-Source esp32` retains its fail-closed hardware gates; it does not fabricate frames.

Recorded-video loops reset temporal state. Repeated entries in replay history are not unique real-world arrivals. Use a webcam or an appropriately long video to demonstrate dwell naturally. Source labels distinguish video files, webcams and the unverified ESP32 camera.

### Screenshots

The existing project screenshot below shows genuine **historical event history from the earlier interface**, before this release's redesign. It is already versioned; it is not evidence of the current models or camera hardware.

![Historical SentinelAI event timeline](screenshots/slide10-dashboard-event-log.png)

Fresh dashboard, event-inspector and mobile screenshots are created by the opt-in release verifier and remain under ignored `data/`, since frames can contain private people or locations:

```powershell
& .\.venv\Scripts\python.exe scripts/verify_release.py --source 'C:\path\to\authorized-video.mp4' --base
```

This uses real cached models with a local video and separate validation storage; it never opens serial or a webcam. The report labels simulated adverse-state browser checks separately. To generate your own webcam end-to-end screenshot, first run:

```powershell
& .\scripts\run_presentation.ps1 -MaxSeconds 240
```

Then in another terminal:

```powershell
& .\.venv\Scripts\python.exe scripts/verify_presentation.py
```

This optional real-model/browser check expects the laptop webcam by default. Its results and screenshot are saved in a new directory under `data/presentation/validation_*`; recorded-video validation requires `--expected-source video_file`. Only publish screenshots you have permission to share.

## Tests and firmware builds

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
# Optional browser and firmware tooling:
& .\.venv\Scripts\python.exe -m pip install -r requirements-verification.txt
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/uart_probe
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/camera_uart_probe
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/uart_programmer_bridge
# Inert camera-driver reference only; not a physical camera target or upload image:
& .\.venv\Scripts\python.exe -m platformio run --project-dir esp32/camera_capture
```

Firmware commands compile only; they do not upload. Ordinary tests use synthetic images/records and mocked model/serial responses. They do not demonstrate physical hardware or model quality. Fresh results and the distinction between unit tests, genuine inference, browser checks and historical validation are recorded in [release validation](docs/RELEASE_VALIDATION.md).

## ESP32 status and safe setup

The original telemetry sketch is preserved under `esp32/SentinelTelemetry`. Historical physical tests established USB telemetry, ping and alert acknowledgements on the primary DevKit. No physical actuator or on-device AI is claimed.

**ESP32 camera integration is experimental. Physical sensor initialization, firmware flashing, genuine JPEG reception, continuous video, dashboard display, and AI processing of real ESP32-origin frames have not been verified end to end.** Camera-board power/regulator routing, the second DevKit's supply/current budget, UART0/IO0/reset routing and programming controls remain unverified. Real camera PING/PONG, initialization/PID and image capture have not passed. COM9 must not be treated as a direct camera programmer.

Prepared host camera-stream framing/decoding and explicit `-Source esp32` now exist, but camera mode fails closed until independent physical approval and live diagnostics pass. `scripts/check_esp32_camera.py` reports the current blocked stages without opening serial. Installed probe/telemetry firmware does not emit capture packets. A gated `esp32/camera_capture` core now implements real driver/PID/JPEG transport logic offline, but its included reference image is deliberately inert and is not a build for the unidentified physical camera.

The UART probe explicitly uses primary RX16/TX17; the camera responder and binary bridge are separate, compile-tested projects. Do not flash, erase, energize or alter wiring based on compilation. Keep real telemetry and fresh recoverable backups intact. Read the complete [hardware setup and reported wiring guide](docs/HARDWARE_SETUP.md), then [firmware development](docs/ESP32_SETUP.md) and [first-JPEG milestones](docs/ESP32_FIRST_JPEG.md).

Current user-reported UART connections are primary GPIO17/TX2 -> camera U0R, camera U0T -> primary GPIO16/RX2, and common GND. Secondary DevKit 5V/GND connects to camera 5V/GND as an unverified intended supply path. Neither continuity nor voltage/current capability has been independently checked. The primary connects to laptop USB; the secondary to a power bank. Exact camera revision, sensor and pin map remain unknown. Earlier conflicting wiring accounts are preserved as history.


## Pipeline and analysis lifecycle

YOLO11n and ByteTrack share one model invocation per frame; the standalone `Detector` remains a compatibility utility. Confidence defaults to 0.5 and IoU to 0.7. ByteTrack IDs connect boxes to state histories. The state manager computes motion using elapsed timestamps (normalized to a 30 FPS reference); loitering and unattended durations use elapsed time. Rules detect entry, exit, zone changes, dwell, rapid motion and unattended-object candidates. These are heuristics, not established intent or ownership. Disconnections and video rewinds reset temporal state.

Each deterministic event is inserted into SQLite with its source metadata and a unique saved JPEG path. Missing image writes leave an event with no evidence reference. Selected event types enter a bounded priority queue, deduplicated while pending. Queue overload is explicitly skipped. The record distinguishes queued work from active processing and retains measured processing duration (including model-readiness wait when applicable). The worker checks the queued image SHA-256 and the event association; results retain event ID, task, model, prompt, checked time, hash, raw observation and error/status. Shutdown marks pending work cancelled. Failed checks can be retried from the API; inference timeouts require restarting the worker/application.

**Florence-2** processes the selected saved image. With the local trained adapter it retains the training-compatible yes/no/unknown prompt. Without that adapter it uses the supported `<DETAILED_CAPTION>` task and parses its task-keyed output; the presence answer remains `unknown`. The base caption has a bounded 64-token minimum budget. This task follows the [upstream Florence model card](https://huggingface.co/microsoft/Florence-2-base-ft). Still images cannot verify running, ownership, dwell time or an exit. Successful output stays `inconclusive`; confidence is never fabricated. Invalid inputs, corrupt images, malformed output, dependency errors and model timeouts remain distinguishable from success.

**SmolLM2** has two answer styles. **Written explanation**, the dashboard default, generates a short paragraph from supplied event records and available visual descriptions. **Recorded facts** retains constrained source-ID selection and deterministic fact rendering from SQLite. The frame-description panel separately explains Florence's caption of the saved snapshot; the language model does not see pixels. Generated prose is labelled as interpretation, references outside supplied records are rejected, and source links come from the host. The small model may still produce inaccurate wording: inspect the image rather than treating its prose as verified fact. Records are removed whole to fit 1,536 input tokens; generation defaults to 96 tokens. Missing data, unusable output and service errors produce explicit supplied-data fallbacks. No previous generated explanation is reused as evidence.

## Configuration and storage

The launcher always uses `config.presentation.yaml`. Direct `python -m backend.main` uses ignored `config.yaml`, or `--config PATH` / `SENTINEL_CONFIG`. `SENTINEL_LLM_MODEL` overrides the configured LLM model ID. Paths resolve against the repository root.

| Section | Relevant settings |
| --- | --- |
| `camera` | `source`, `width`, `height`, `fps`, `max_read_failures`, `reconnect_delay_s` |
| `detector` | `model_path`, `confidence_threshold`, `iou_threshold`, `device` |
| `event_engine` | `zones`, `missing_timeout_s`, `loitering_threshold_s`, `running_speed_px_per_frame`, association/separation distances, `unattended_threshold_s` |
| `vlm` | `enabled`, `base_model_id`, `adapter_dir`, `runtime_path`, `queue_max_size`, `event_types`, token/load/inference limits |
| `llm` | `enabled`, `model_id`, `context_event_limit`, `max_new_tokens`, `cpu_threads`, timeout limits |
| `database` / `evidence` | `path` / `output_dir` |
| `api` / `esp32` | host/port; optional telemetry configuration (disabled for presentation) |

Supported presentation sources: integer webcam index, existing video file, HTTP(S) stream, explicitly gated `esp32`. Recorded video loops by default; `-NoLoop` stops at EOF. Backend direct mode also accepts RTSP. There is no automatic source substitution. Video timestamps advance from media position; loop boundaries start a new temporal segment. Webcam processing is synchronous with YOLO; slow AI runs separately in subprocesses. The implementation makes no capture FPS or latency guarantee.

Presentation storage: `data/presentation/sentinelai.db` and `data/presentation/events/`. Direct defaults: `data/sentinelai.db` and `data/events/`. SQLite migrations are additive; reads and writes share a serialized connection. There is no automatic evidence retention policy; monitor disk use and archive data while the application is stopped.

## Confirmed interfaces

| Method / endpoint | Purpose |
| --- | --- |
| `GET /` | Dashboard |
| `GET /api/health`, `GET /api/models` | Source freshness, pipeline and model lifecycle/errors |
| `GET /api/events?limit=50&event_type=LOITERING` | Bounded event history; optional `query` description substring search |
| `GET /api/events/{event_id}` | Record, evidence reference and VLM metadata |
| `GET /api/stats`, `GET /api/event_types` | Counts and supported types |
| `POST /api/events/{event_id}/verify` | Queue saved evidence; enforce configured evidence directory |
| `POST /api/llm/query` | JSON `question`, optional `event_type`, `limit` (1 to 20), `mode` (`facts` or `explain`) |
| `POST /api/scene`, `GET /api/scene` | Queue/read an actual fresh-frame caption and written scene explanation |
| `GET /api/frame.jpg` | Fresh annotated preview; stale frames return 404 |
| `GET /evidence/{filename}` | Saved JPEG evidence |
| `WS /ws/stream` | Live track/event/frame metadata; preview images use REST |

QA examples: "When was the latest loitering event?", "Show event #42", "What happened in the last five minutes?". Around-time queries require an ISO timestamp with explicit timezone. Retrieval is deterministic keyword/time/ID filtering, not general semantic search. A query about unavailable facts returns records plus explicit uncertainty rather than invented facts.

## Repository map

```text
backend/       camera, tracking, state/events, evidence, SQLite, AI workers, API
 dashboard/    browser UI (index.html)
 scripts/      presentation, validation, model setup, experimental diagnostics
 tests/        deterministic regression tests with synthetic/mock inputs
 docs/         operations, validation, model and hardware guides
 esp32/        preserved telemetry, camera references, probes and bridge firmware
 config.presentation.yaml   full-AI webcam demo on localhost:8010
 requirements*.txt          host and isolated Florence dependency pins
```

The experimental camera milestones remain: resolve carrier/power/sensor/GPIO identity with competent electrical inspection; authorize a separate hardware session; identify and build the correct target; verify flashing, sensor initialization and one genuine JPEG; then establish continuous frames, dashboard provenance and local AI processing. No physical step is part of this presentation task.

## Limitations and troubleshooting

- **Video missing/unreadable:** supply an authorized local file or use `-Source 0`; check permissions and codec support.
- **Camera unavailable:** close other webcam applications and check Windows camera permissions. Reconnect/error states are exposed; stale frames are hidden.
- **Port 8010 busy:** stop the existing backend before starting another launcher.
- **Models loading/error:** inspect the dashboard and `data/logs/vlm-worker.log` / `llm-worker.log`. Ready means weights loaded; completed-inference counters establish requests actually completed. Missing weights need the explicit setup commands above.
- **Florence compatibility:** install the pinned overlay; do not downgrade the main environment globally. Presence answers are uncalibrated and do not validate elapsed activity.
- **LLM scope:** written explanations use supplied records or Florence captions and may be inaccurate. Recorded-facts mode preserves validated source selection and SQLite fact rendering. Neither mode is a general chatbot; unusable model output has a visible fallback.
- **CPU contention/queue full:** FPS varies; event checks may be skipped by the bounded queue. No throughput guarantee is claimed.
- **Accuracy:** representative detector/event/tracker field accuracy is not measured. Existing adapter evaluation did not establish an improvement. See [accuracy evaluation](docs/ACCURACY_EVALUATION.md).
- **Local-only security:** use one backend worker and the localhost presentation binding. This is not an authenticated public hosting configuration.

## Repository hygiene and licensing

Source, tests, documentation, firmware and dependency manifests are versioned. Environments, caches, secrets, local configuration, databases, logs, evidence, videos, datasets and model weights are excluded. Do not add those files with `git add -f`.

This repository preserves its existing Git history. Generated files previously committed in that history remain there; the cleaned tip stops tracking them without deleting local copies. No project redistribution license has been selected. Third-party models and dependencies retain their upstream license terms.

## Technology and development

Python 3.13, OpenCV, Ultralytics YOLO11n/ByteTrack, SQLite, FastAPI/Uvicorn/WebSocket, plain HTML/CSS/JavaScript, PyTorch/Transformers and Arduino-ESP32/PlatformIO. AI executes on the host; the ESP32 is not an inference accelerator. The managed AI workers currently use CPU; the detector supports configured CPU/CUDA selection. External web fonts are not required by the dashboard.

Use [CONTRIBUTING.md](CONTRIBUTING.md) for checks and change review, [SECURITY.md](SECURITY.md) for local access/privacy boundaries, and [AI_MODELS.md](docs/AI_MODELS.md) for model lifecycle and interpretation. No source redistribution license has been selected; there is intentionally no new `LICENSE` file.

Additional local checks:

```powershell
& .\.venv\Scripts\python.exe -m compileall -q backend scripts tests
& .\.venv\Scripts\python.exe scripts/check_repository.py
git diff --check
# If Node.js is installed (optional syntax check, not a runtime dependency):
node --check dashboard/dashboard.js
```

The publication checker is a local heuristic scan of tracked/unignored candidates; review the staged diff as well. No code or footage is uploaded by that checker. New databases, evidence, logs and model caches are generated locally and stay ignored. There is no configured Python linter/formatter; compile checks, regression tests, JS syntax and diff checks are the available gates.

## Roadmap

- Establish a verified electrical/programming route and real camera PID/JPEG evidence before any hardware video claim.
- Evaluate detector/tracker/event accuracy and visual-model calibration on representative authorized data.
- Add authenticated access before considering network deployment beyond a trusted local machine.
- Design a user-controlled evidence retention policy; no automatic deletion occurs today.


## Continuous integration

GitHub Actions runs the host contract suite on Windows with Python 3.13 and `requirements-core.txt`. These tests use controlled fixtures and mocked model/serial boundaries; CI does not open cameras, flash firmware, download model weights or establish hardware performance. Physical-device and real-model validation remain the separate procedures documented above.
