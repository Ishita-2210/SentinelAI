# Presentation outline and viva notes

1. **Problem and motivation.** Continuous video is difficult to review. SentinelAI produces timestamped, evidence-linked event records on a local host.
2. **Design principle.** Pixels -> detections -> tracks -> states -> temporal rules -> evidence -> structured memory -> explanations.
3. **Hardware boundary.** Show the actual ESP32-WROOM-32 board. Its demonstrated function is USB telemetry and alert acknowledgement. A separate camera PCB is now reported wired by UART, but power and physical PING/PONG are not verified. Heavy inference runs on the laptop.
4. **Computer vision.** YOLO11n predicts classes, confidence and xyxy boxes. ByteTrack assigns IDs in the same inference path. Discuss false detections rather than claiming universal accuracy.
5. **State and events.** Explain dwell timers, zone transitions, missing-track grace, normalized image motion and unattended-object heuristics.
6. **Evidence and memory.** Every saved event gets a database ID and JPEG path. Show that a fresh API retrieves records after the detector stops.
7. **Dashboard.** Demonstrate actual camera/device status, tracks, event filters, thumbnails and history. Separate optional VLM evidence from the deterministic event.
8. **VLM experiment.** Base 22/40 correct (55.0%); adapter 23/40 (57.5%); both fail all 3 UNKNOWN examples. Always-yes baseline is 24/40 (60%). Show cross-split image leakage and explain why the adapter is not an accuracy claim.
9. **Verification.** Show focused test output, a real 30-frame webcam trace with stable person ID, browser report and evidence. Synthetic scenarios test logic only.
10. **Live demo.** Start host, show actual ESP32 status, enter the zone, wait 10 seconds, open evidence, stop host, restart API to show persistence.
11. **Limitations.** Small/leaky VQA dataset, no labeled detection benchmark, no IDF1/HOTA evaluation, pixel-scale motion/proximity thresholds, optional AI compatibility, simple USB telemetry.
12. **Future work.** Acquire representative independent videos, group splits by original image/video, annotate events and boxes, calibrate thresholds on validation only, expand genuine ambiguity labels and evaluate before further training.

## Short speaking script
?SentinelAI uses a laptop for vision inference and an ESP32 as a connected embedded telemetry and alert endpoint. YOLO supplies detections, ByteTrack supplies identity, and temporal rules determine events. Each record links to an actual evidence image. I verified the software path and report the experimental VLM's weak results rather than using it as the event authority.?

## Viva questions
- **Why event-driven?** Expensive visual-language analysis is invoked only for selected event keyframes, while deterministic tracking/state updates process the stream.
- **Why not inference on the ESP32?** The inspected module's compute and memory are inappropriate for Florence and the host vision stack; it supplies an embedded communication/control boundary.
- **Does the camera board supply tested video?** No. The separate camera board has a reported inserted ribbon, but its power/pinout and UART path are unverified. Tested sources are the laptop webcam and labelled fixtures.
- **What survives restart?** SQLite event metadata and JPEG evidence. Tracking identity and live temporal state are process-local.
- **Why does standalone API work now?** Its lifespan initializes its own database and retrieval dependencies; it does not depend on main having run in the same process.
- **What does RUNNING mean?** Rapid image-plane motion above a configured threshold, normalized to elapsed time. It is not a calibrated physical speed or validated action-recognition model.
- **How do you handle occlusion?** ByteTrack and a missing-track grace reduce brief-loss exits; longer occlusion can still fragment IDs.
- **Can a still image prove loitering?** No. Duration comes from state history, while optional VLM checks only visible presence.
- **Is 57.5% good?** No. It is below the 60% majority baseline, and UNKNOWN abstention failed. The adapter remains experimental.
- **Why not retrain immediately?** Split leakage, very few UNKNOWN labels and domain mismatch make new scores unreliable until data quality and evaluation improve.
- **Are synthetic results field accuracy?** No. They establish deterministic software behavior under known tracks, not detector or real-world event performance.
- **What if ESP32/VLM/local LLM disconnects?** Optional device/AI failures are reported separately; host capture, deterministic events and storage continue.
- **What does the local LLM contribute?** Direct SmolLM2 inference selects a constrained retrieved event ID. SQL fields supply the factual answer and evidence links; generated free-form claims are not displayed. Semantic ranking quality remains unmeasured.

Use screenshots under data/evaluation only as recorded results. Present the still-image fixture explicitly as an integration demonstration, and use the real webcam for live claims.

## Later integration evidence
Florence loaded the preserved adapter and saved a raw presence answer. Direct local SmolLM2 generated validated event-ID JSON; both models ran concurrently with frame processing, API and dashboard QA. No Ollama is used. Show data/integration/end_to_end.json and dashboard_local_ai.png. Models are opt-in; see LOCAL_MODELS_SETUP.md. Do not present the compiled UART probe as a physical camera demonstration.
