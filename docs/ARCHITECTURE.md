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

Heavy inference runs on the laptop. The DevKit has historically demonstrated USB telemetry and alert acknowledgement only. Camera supply, header mapping and real UART PING/PONG remain unverified; UART JPEG integration has not been attempted.

## Contracts and lifecycle

CameraSource returns BGR frames or failure, with bounded network opening/reads and file EOF handling. YOLO performs one model.track call per frame. ByteTrack IDs feed state history, elapsed-time motion and zone visits. Missing tracks use a grace period; dwell resets on re-entry. Capture/inference failures and video rewinds reset temporal continuity. Unattended ownership and RUNNING remain heuristics.

Evidence is stored before the event row. Additive database migrations preserve existing records, including separate VLM status/prompt/raw response/model/adapter/error/time fields. VLM output never changes the deterministic event. Main publishes persisted IDs and evidence paths; dashboard history polling recovers missed live messages.

The backend owns two optional child processes using the existing .venv Python, private JSON IPC and local cached weights. Florence alone imports the existing Transformers 4.49 compatibility overlay; SmolLM2 uses main-environment Transformers 5.17. No Ollama, external inference server, paid API or runtime weight download is used.

Processes expose disabled/loading/ready/error, actual model IDs, adapter status and errors. Loading and inference occur outside the frame loop. Each model permits one active request; VLM work has an eight-entry priority queue with deduplication. Timeouts fail explicitly; shutdown stops workers and marks queued checks cancelled.

Auto VLM checks selected loitering/unattended events; a manual API check accepts saved evidence within the configured root. Still images establish presence only, never elapsed activity. All visual conclusions are labelled uncalibrated/inconclusive with null numeric confidence.

Question filters cover selected event types/IDs, recent time windows, latest events, VLM results and timezone-qualified around-time queries. The small LLM chooses a permitted retrieved ID using constrained decoding; it cannot supply factual prose or invent references. Remaining records are retained. SQL facts and evidence links are rendered deterministically, with transparent fallbacks on unavailable/invalid model output. This is extractive QA, not general language reasoning.

Main injects shared database/retrieval/AI resources into the API. Standalone API lifespan creates only resources it owns and closes them on exit. A single backend application/worker is supported. Model weights and config/evidence/database paths resolve from the repository. Dashboard requests use its own HTTP/WebSocket origin.

Source provenance distinguishes webcam, file and network stream; USB device presence never implies ESP32-camera video. The latest model demonstration used the repeated-photo integration fixture. Real hardware input requires the staged checks in ESP32_SETUP.md.
