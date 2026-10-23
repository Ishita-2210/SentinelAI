# Implemented SentinelAI architecture

```text
Webcam / explicit video file / supported network source
  -> YOLO11n + ByteTrack -> StateManager -> deterministic EventEngine
  -> saved JPEG + SQLite event ID
  -> FastAPI / WebSocket -> dashboard and evidence links

Saved keyframe -> bounded priority queue -> managed Florence worker
  -> separate SQLite VLM metadata (inconclusive presence hypothesis)

Question -> deterministic SQL filters -> retrieved event records
  -> managed direct Transformers SmolLM2 worker (constrained ID ordering)
  -> strict ID validation -> factual answer rendered from SQLite + sources

Host event -> bounded USB alert queue -> DevKit telemetry firmware -> ACK

Desired, not yet operational:
camera -> camera ESP32 UART0 -> DevKit UART2 -> USB -> host CameraSource
```

Heavy inference runs on the laptop. The DevKit has historically demonstrated USB telemetry and alert acknowledgement only. Camera supply, header mapping and real UART PING/PONG remain unverified. The host UART JPEG receiver and gated firmware references are implemented and tested offline; no genuine camera image has been received. See [hardware setup](HARDWARE_SETUP.md).

## Contracts and lifecycle

CameraSource returns BGR frames or failure, with bounded network opening/reads and file EOF handling. YOLO performs one model.track call per frame. ByteTrack IDs feed state history, elapsed-time motion and zone visits. Missing tracks use a grace period; dwell resets on re-entry. Capture/inference failures and video rewinds reset temporal continuity. Unattended ownership and RUNNING remain heuristics.

Evidence is stored before the event row. Additive database migrations preserve existing records, including separate VLM status/prompt/raw response/model/adapter/error/time fields. VLM output never changes the deterministic event. Main publishes persisted IDs and evidence paths; dashboard history polling recovers missed live messages.

The backend owns two optional child processes using the existing .venv Python, private JSON IPC and local cached weights. Florence alone imports the existing Transformers 4.49 compatibility overlay; SmolLM2 uses main-environment Transformers 5.17. No Ollama, external inference server, paid API or runtime weight download is used.

Processes expose disabled/loading/ready/error, actual model IDs, adapter status and errors. Loading and inference occur outside the frame loop. Each model permits one active request; VLM work has an eight-entry priority queue with deduplication. Timeouts fail explicitly; shutdown stops workers and marks queued checks cancelled.

Auto VLM checks selected loitering/unattended events; a manual API check accepts saved evidence within the configured root. Still images establish presence only, never elapsed activity. All visual conclusions are labelled uncalibrated/inconclusive with null numeric confidence.

Question filters cover selected event types/IDs, recent time windows, latest events, VLM results and timezone-qualified around-time queries. The small LLM chooses a permitted retrieved ID using constrained decoding; it cannot supply factual prose or invent references. Remaining records are retained. SQL facts and evidence links are rendered deterministically, with transparent fallbacks on unavailable/invalid model output. This is extractive QA, not general language reasoning.

Main injects shared database/retrieval/AI resources into the API. Standalone API lifespan creates only resources it owns and closes them on exit. A single backend application/worker is supported. Model weights and config/evidence/database paths resolve from the repository. Dashboard requests use its own HTTP/WebSocket origin.

Source provenance distinguishes webcam, file and network stream; USB device presence never implies ESP32-camera video. The latest model demonstration used the repeated-photo integration fixture. Real hardware input requires the staged checks in ESP32_SETUP.md.

## Release reliability and UI

The vanilla HTML/CSS/JavaScript dashboard uses same-origin requests and system fonts. Event history is reconciled by persisted ID, with one in-flight refresh per poller. The native dialog shows original evidence, source metadata, actual Florence task/output/hash and persisted processing duration. Source links from SmolLM2 open the same inspector. Text and attribute values are escaped; filenames are URL-encoded rather than interpolated into executable handlers. Failed image loads retain the event record and show an unavailable state.

WebSocket publication has one coalesced latest-frame slot, a 64-entry notification queue and one drain task. Slow clients have bounded send time and are pruned without holding fast clients. A notification can be displaced under sustained load; SQLite/REST polling recovers authoritative history. This does not guarantee delivery of every live frame. Capture remains synchronous with detector/tracker work; expensive visual/language inference runs separately.

VLM events now distinguish queued and processing state. The additive `vlm_duration_ms` column stores successful processing duration, including readiness wait. Old records remain null and intact. `last_inference_ms` records a successful model request duration; LLM responses include the measured duration of their own successful request. No latency is synthesized for fallbacks or old records.

## Frame descriptions and stable live panels

The scene endpoint atomically snapshots the preview JPEG, sequence and capture age, rejects stale input, saves the real annotated image and enqueues one scene job in the existing bounded VLM priority queue. No synthetic event row is inserted. The same Florence process captions with the base task, temporarily bypassing a loaded presence adapter; SmolLM2 then writes an interpretation of that caption. The scene result retains its exact source/hash/image link and separate model statuses. The latest result is in memory; snapshot files stay in the existing local evidence directory. Dashboard automatic refresh is optional and occurs every 30 seconds, not per frame.

Event QA offers explicit written-explanation and recorded-facts modes. Generated descriptions are model interpretations; deterministic facts and validated source ordering remain available independently. Track rows are reconciled by ID, and tracking/history/results/evidence panels reserve space and scroll internally. Growing lists and longer model/status text therefore do not push adjacent cards up and down.
