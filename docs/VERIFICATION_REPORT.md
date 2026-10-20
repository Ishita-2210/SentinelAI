# Verification report

Date: 20 October 2026, Asia/Kolkata. Existing core reports remain under data/evaluation; the later local-AI integration reports are under data/integration.

| Boundary | Observed result | Evidence |
|---|---|---|
| Final regression suite | 116 passed, one upstream deprecation warning | data/integration/final_pytest.log |
| Backend compilation / dependency consistency / whitespace | See final logs | data/integration/final_compile.log, final_dependencies.log, final_whitespace.log |
| Real webcam | 30 frames, 640x480; person ID 1 in all processed frames | data/evaluation/webcam_capture.json, webcam_frames.jsonl |
| Saved evidence, SQLite, API/WebSocket, browser, restart | Passed historical core run | data/evaluation/demo_verification.json, webcam_demo/demo_verification.json |
| Deterministic event logic | 13 sequences, 23 expected events, no mismatches | data/evaluation/events.json |
| VLM accuracy comparison | Base22/40; adapter23/40; UNKNOWN0/3 both | data/evaluation/vlm_compatible/metrics.json |
| Dataset integrity | Records unchanged; duplicate-image leakage disclosed | data/evaluation/dataset_audit.json |
| Real Florence runtime | Adapter loaded; raw yes; inconclusive persisted presence hypothesis | data/integration/end_to_end.json |
| Real direct local LLM | SmolLM2 generated10 tokens; validated permitted event ID | data/integration/end_to_end.json |
| Concurrent model/perception/API | Both ready by13.12s; frame counter113->153 during QA; health2..8.4ms in this run | data/integration/end_to_end.json |
| Dashboard QA and sources | Real Edge run; no JavaScript errors | data/integration/end_to_end.json, dashboard_local_ai.png |
| Historical DevKit build/upload/USB telemetry/ACK | Physically passed earlier | data/evaluation/firmware_status.json, esp32.json |
| Latest integrated DevKit availability | COM9 absent; disconnected shown while perception continued | data/integration/end_to_end.json |
| New DevKit UART probe | Compiled only; not flashed | data/integration/uart_probe_build.log |
| UART checker | Simulated nonce/timeout/power-gate contract tests only | tests/test_camera_uart_probe.py |
| Camera supply and UART PING/PONG | Unverified; physical stage blocked | docs/ESP32_SETUP.md |
| Camera JPEG -> host | Not implemented/tested for UART; deferred until power and PING/PONG pass | docs/ESP32_SETUP.md |

The real local-AI run used data/demo/still_image_fixture.avi, a video repeating a real photo. YOLO/model inference, database updates and browser requests were real; temporal input was synthetic and was not an ESP32 stream. The screenshot predates a later CSS scroll-height adjustment. All inference uses local cached weights; downloads were an explicit setup operation.

Unconstrained tiny-LLM generation initially failed the output schema and correctly fell back to stored facts. The constrained final run passed. See data/integration/local_models.json for the initial standalone outcome and end_to_end.json for the final integrated result; do not confuse them.

Current software, model selection and launch commands: LOCAL_MODELS_SETUP.md. Hardware gates and existing reported wires: ESP32_SETUP.md. Full completion/limitations report: LOCAL_AI_INTEGRATION_REPORT.md.

Original datasets/adapters and the DevKit flash backup are preserved. No retraining, destructive Git operation or camera-board flash was performed. Changes remain in the existing feature branch.
