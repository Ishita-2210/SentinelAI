# ESP32-only completion status

## Current command and result

```powershell
& D:\SentinelAI\scripts\run_presentation.ps1 -Source esp32
```

Historical ESP32-only work is preserved here. The current presentation default is laptop webcam 0; ESP32 must be selected explicitly. No webcam/file source is substituted if it fails. Today this command correctly stops at preflight, before models or serial access: the overheating concern, actual carrier configuration, installed capture firmware and fresh physical diagnostics remain unresolved. Do not reconnect the uncertain hardware to try to clear this error. Other sources remain explicitly selectable for existing users, but cannot enter or qualify as ESP32 frames.

## Completed software

- Existing CaptureService calls the Espressif camera driver, reports real driver errors/PID, captures JPEG buffers, and emits bounded SNC1 status/JPEG packets. The actual camera configuration remains private/unfilled; no carrier/sensor is assumed. The UART-only responder is a generic reference target, not camera capture firmware. The old one-frame AI-Thinker hypothesis is retained as a hypothesis and was neither selected nor flashed.
- Framing validates magic/version/type/flags, length, CRC32 and JPEG dimensions, handles fragmented/corrupt/truncated packets, resynchronizes after noise and bounds memory/timeouts. Sequence/session/capture counters reject replay and reset continuity on a real reconnection.
- UART reception runs independently of YOLO/VLM/LLM, with a one-frame latest queue, dropped-frame accounting, bounded retries and cleanup. Normal low-rate inter-frame waits do not reset tracking. Exact first-JPEG export never re-encodes or overwrites existing evidence.
- Received frame/event metadata now distinguishes `live_serial` from `software_fixture`. An injected stream cannot qualify as physical merely by setting a result status. API camera verification requires agreeing receiver/frame provenance and fresh preview; a standalone `esp32_camera_verified` flag is ignored. This is controlled code provenance plus operator-established origin, not cryptographic sensor attestation.
- Live diagnostics must contain matching receiver and last-frame provenance, decoded-frame/PID metrics and stable delivery, not just `state:passed`. A run with reconnects does not qualify as continuous. Corrupt/malformed diagnostic records fail cleanly.
- API health exposes camera stages, RX/decoded FPS, resolution, age, drops and transport errors. Preview generation does not itself claim browser rendering. The serial checker explicitly leaves dashboard, pipeline/evidence and AI checks untested.
- ESP32-mode QA retrieves only live-serial evidence for the selected camera, filtering before SQL LIMIT. It cannot answer from newer laptop/fixture/other-camera rows. Manual VLM verification rejects events outside that scope. Existing non-ESP32 history behavior is retained.
- `scripts/verify_presentation.py` defaults to webcam validation; future camera validation requires explicit `--expected-source esp32_camera_uart`. In a later qualified live session it checks continuous receiver evidence, changing preview, browser/WebSocket behavior, fresh Florence results and SmolLM2 answers whose evidence belongs to that camera. It does not start a camera itself or attest a scene from flags alone. It was not run against physical equipment in this task.

## Actual validation in this task

**246 passed,0 failed**, one upstream Starlette deprecation warning. Tests cover valid/corrupt/truncated/oversized packets, deadlines, reconnects/queues/cleanup, injected-frame handoff to the existing pipeline, provenance/QA isolation and source-selection refusal. All frame-driven tests use generated images/injected streams; none establish physical camera capture.

Two reference builds passed: `esp32/camera_capture` (`reference_compile_only`, inert entry point) and `esp32/camera_uart_probe` (`reference_esp32dev`, UART responder only). Neither identifies the actual carrier or establishes a deployable camera image. Dashboard JavaScript syntax compiled in a headless browser without executing the application. Default and explicit ESP32 `-Check` both returned2 before source access. All six original/recovery artifact pairs hash-match. Telemetry source, tested firmware and recovery files were not changed. No webcam/recorded demonstration or hardware operation was used to satisfy this task.

Private evidence: `data/hardware_identification/esp32_only_completion/validation.json`, build logs and preflight output.

## Physical evidence and minimum next action

The supplied14/14 isolated adapter loopback was real historical evidence for ESP-A in that setup. CAM ROM identification has not passed; passive CAM listening received zero bytes. Neither fact establishes CAM power or failure cause. Current port availability was not probed. No flash/erase, GPIO operation, serial opening/transmission, power experiment or rewiring occurred in this task. Sensor PID, genuine JPEG, continuous ESP32 preview and AI processing of ESP32-origin evidence remain **unverified**.

**Next action:** take the disconnected CAM and its actual power arrangement to an electronics technician/lab for unpowered short/regulator/power-route inspection after the reported severe heating. Because there is no meter, another serial test cannot replace this. Controlled supply/current/rail checks belong to that qualified inspection, after the input/path is identified. No supply swap or renewed power is instructed here.

The single unresolved board-specific software definition is the actual carrier/FPC-to-ESP32 GPIO map (and compatible ribbon/sensor assembly), to be established from a matching revision schematic or measured connectivity. Existing references only support AI-Thinker-style similarity. The bundled driver can identify supported sensors at runtime; selecting an arbitrary map or presuming OV2640/OV3660 would not establish compatibility.

After electrical clearance and an explicit hardware authorization: validate the actual UART/boot/reset routes; manually select ROM download mode; obtain CAM chip/flash identity; compile the independently established camera target/configuration; program only CAM; restore normal boot; obtain matching PONG/init/PID and a changing-scene JPEG; qualify sustained frames; then run the ESP32-only launcher and end-to-end verifier. Each stage remains separate.

ESP-A may provide a direct USB-UART adapter with its own EN held low, without touching its flash, if the actual CH9102/header routes and common ground are confirmed. The most recent reported route is GPIO3/RX0 -> CAM U0R, GPIO1/TX0 <- CAM U0T with manual CAM IO0/reset; the older GPIO16/17 firmware-relay plan is historical. USB DTR/RTS do not provide CAM reset in that route. The existing manual `camera_chip_id.ps1` already prepares no-reset/no-stub ROM ID commands for a later authorized session, but is suspended now. No trustworthy upload command can be finalized until the actual target image, flash identity and power/programming path exist. No new USB programmer is automatically required by the adapter loopback result.

The final requested physical-video goal has **not** been achieved. Software preparation/test success does not change that result.
