# Final improvement pass ? 20 October 2026

See [fresh validation and limitations](FINAL_VALIDATION.md) and the [implemented analysis lifecycle](../README.md#pipeline-and-analysis-lifecycle). The official source is laptop webcam 0. The adapter prompt is preserved; base Florence now uses parsed `<DETAILED_CAPTION>` observations. VLM results retain task and exact image SHA-256, with association checks and request-error retry. SmolLM2 receives explicit missing evidence and unverified visual observations; whole-record context reduction preserves the question. Factual prose remains rendered from SQLite. Expired state/event memory, evidence filename collisions and invalid frame inputs have regression coverage.

The remaining sections are historical records; their counts and operating defaults do not replace the fresh report.

# Historical ESP32-only update

At that earlier stage ESP32 was the default source. 246 regression tests and two reference builds passed; no physical camera stage passed. Receiver/fixture provenance, source-scoped QA, stage metrics and the future ESP32 end-to-end verifier were strengthened. See [ESP32_ONLY_STATUS.md](ESP32_ONLY_STATUS.md) for implemented versus physically observed results. Earlier laptop results below are historical and do not satisfy the ESP32-video goal.

# Local AI integration and UART hardware completion report

## Latest deadline validation ? current working tree

The full regression suite passed **236 tests** with one upstream Starlette deprecation warning. Camera framing/error/timeout/reconnect/buffering/provenance and pipeline integration tests use generated data or injected streams; they are not physical camera evidence. The inert `esp32/camera_capture` reference build passed (22108bytes RAM,268932bytes application); no actual-camera deployment build is identified or approved. Existing telemetry was not rebuilt or flashed. All six original/recovery artifact pairs still match their recorded SHA256 values; the historical full flash copy is not a current-device readback.

A60-second full-AI-enabled webcam run opened1280x720, processed real person tracks and committed10 events with10 existing evidence JPEGs. Preview sequence and bytes advanced; the headless dashboard received43 WebSocket messages without browser JavaScript errors. Models were still loading for part of this short run, so it was not counted as completed Florence inference. This run exposed a double-disconnect WebSocket traceback; the fix makes socket cleanup idempotent, and a new regression test covers it.

The subsequent full-AI recorded-laptop-video validation **passed** against the existing launcher with both local models enabled:548 processed frames at verification, fresh Florence inference on saved event336 (`yes`, stored `inconclusive`, no calibrated confidence), browser-submitted SmolLM2 QA (`llm_used:true`, validated source ordering,11 generated tokens), frames506->525 during QA,35 WebSocket messages, zero browser errors, evidence served over HTTP, and preview outage/recovery. Model counters were VLM2/LLM1 at verification. Sources remained `webcam` or `video_file`, `esp32_camera_verified:false`. This is functionality validation, not accuracy validation or ESP32 proof.

Code changes preserve tracking through ordinary slow-UART inter-frame waits while resetting on real reconnect/session changes; reject JPEGs while capture status reports an error; and prevent duplicate WebSocket removal. The verifier now checks source identity, fresh model results and saved evidence, and writes to an explicit/new artifact directory instead of overwriting earlier validation results.

Run `& .\scripts\run_presentation.ps1 -Source 0` from D:\SentinelAI; dashboard http://127.0.0.1:8010. Explicit recorded fallback: `& .\scripts\run_presentation.ps1 -Source data/demo/webcam.avi`. Both retain Florence/SmolLM2 and independently block serial access.

**Hardware hold supersedes earlier manual test instructions:** the user reports CAM became very hot during a3V3 power experiment and has no multimeter. No energizing, serial opening/transmission, GPIO reset, flash, erase or wiring action occurred in this task. Prior ESP-A loopback14/14 establishes the adapter worked in that setup; current CAM power, ROM communication, sensor PID, capture and continuous ESP32 preview remain unverified. Obtain competent unpowered inspection of the overheated CAM/regulator and power wiring before renewed physical testing. The missing build configuration is the actual carrier/FPC-to-GPIO mapping and compatible sensor assembly; AI-Thinker remains a hypothesis, not an identified target. Wi-Fi MJPEG remains the intended later video transport. No genuine ESP32 launch command is currently qualified.

Both bounded application runs exited0. The final corrected run logged clean shutdown without an application/ASGI traceback, and port8010 was released. Final summary: `data/presentation/deadline_validation/summary.json`.

Artifacts: `data/presentation/deadline_validation/webcam_validation.json`, `webcam_dashboard.png`, `persistence.json`, `preservation.json`, and `full_ai/real_ai_validation.json` / `dashboard_ai_enabled.png`. These private local records distinguish live laptop/model validation from simulated receiver tests.



## Current enabled-AI presentation result (supersedes earlier disabled-model defaults)

Use `& .\scripts\run_presentation.ps1` from D:\SentinelAI; use `-Source 0` for the laptop webcam. Dashboard: http://127.0.0.1:8010. The default input is the real recorded laptop video, looped and clearly labelled; no ESP32 camera is substituted. Both local models are enabled in config and explicit launch flags, and physical serial is blocked independently inside the application child. Logs are printed at startup and referenced by `data/logs/presentation_latest.json`.

The full real-inference/browser check passed using the final launcher: changing JPEG bytes and advancing frame sequences; real Florence-2 adapter inference on saved event151 (raw answer `yes`, stored `inconclusive`, no calibrated confidence); real SmolLM2 generation via the browser QA form (`llm_used:true`, `generation_status:validated`, source-linked answer); model inference counters VLM2/LLM1; frame processing advanced759 to777 during QA;33 WebSocket messages; no browser JavaScript errors. A deliberate browser-only404 preview outage hid the old image, then recovered when requests were restored. Validation took64.57 seconds. This is functional verification, not an accuracy evaluation. The screenshot is `data/presentation/dashboard_ai_enabled.png`; complete evidence is `real_ai_validation.json`.

The first180-second bounded application run stopped while an LLM request was in flight and did not establish LLM success. Its failed result is preserved as `real_ai_validation_first.json`. The successful run used the final launcher with two-thread CPU pools and a240-second application window, without a competing regression workload during model validation. No error was suppressed or counted as inference success.

173 regression tests passed (one existing Starlette deprecation warning). All four relevant firmware builds passed without upload. Original telemetry source/environment/tested application/bootloader/partition table/full backup remain hash-matched; see `ai_environment_preservation.json`. No port COM9 was opened and no flash, reset, UART, wire or power operation occurred. Physical camera power/routing/boot controls, ROM access, PING/PONG, sensor PID and image capture remain unverified, with the same gates in ESP32_SETUP.md.

Changes: enabled presentation defaults and event-triggered entry keyframe verification; added the PowerShell launcher and Python preflight/logging/serial guard; added live-preview age/sequence and stale-frame rejection; fixed browser stale-frame handling, preview retry/backpressure/object-URL cleanup, hardcoded footer URL and event-card animation flicker; added successful-inference counters; exposed source/runtime errors; added regression tests for these boundaries. Existing YOLO/ByteTrack/event rules, database schema, local inference providers and telemetry firmware were reused.

Normal model inference stays asynchronous in existing managed workers and does not run on every video frame. Replaying the short clip creates entry events at each rewind; verification uses the existing bounded queue and may visibly skip requests when full. Earlier results/queues in the isolated presentation database are real records from previous demo runs, not unique real-world arrivals. For natural arrival/dwell behavior use the laptop webcam or an appropriately long video. The small LLM selects retrieved source IDs; recorded factual text is rendered from SQLite, not unconstrained generated claims. Florence output is a still-image presence hypothesis and does not validate temporal events.

Date: 20 October 2026. Repository: D:\SentinelAI, existing feature/sentinelai-complete branch. Software integration is verified; the requested physical UART-camera demonstration is not complete.




## Temporary UART programmer preparation

A separate DevKit-only esp32/uart_programmer_bridge and inert-by-default scripts/uart_programmer_bridge.py now prepare fixed115200 binary forwarding through existing GPIO17/16. A single localhost raw TCP session isolates esptool from COM9 DTR/RTS handoff. Camera boot/reset is not controlled by software; verified manual controls and power remain mandatory. No serial port was opened, no board flashed or energized, no wiring changed and no JPEG/pipeline work performed.

The bridge compiled,20 combined host transport/probe simulations passed, and the full regression suite passed131 tests with one existing upstream deprecation warning. These do not establish MCU behavior or ROM/flash success. All original telemetry/probe sources, environments, original full-flash backup and tested telemetry binary are hash-preserved. Full design, control/timeout limits, exact preparation commands and blocked physical prerequisites are in ESP32_SETUP.md. Current evidence is under data/hardware_identification/programmer_bridge_*.

## Latest component-marking follow-up

The user reports "1117C 33 D420" on the regulator and "AP MEMORY 6404L-3SQR" on the memory IC. Datasheets support a probable fixed 3.3V 1117-family LDO and AP Memory APS6404L-3SQR 64-Mbit (8-MiB) PSRAM. Exact regulator manufacturer/pinout and actual 5V input routing are not established. These readings supersede earlier photo-only identification limits; they are not physical electrical measurements.

The next step is an orientation-labelled unpowered regulator-to-header resistance map, interpreted against an identified component or matching PCB schematic. The only available DevKit is not approved as camera power or a working programmer. No UART test, flash or pipeline change occurred. See ESP32_SETUP.md and data/hardware_identification/component_marking_findings.json for evidence and current gates.

## Hardware research follow-up: 20 October 2026

The reported 3V3/IO16/IO0/GND/VCC/U0R/U0T labels now support AI-Thinker-style ESP32-CAM as the closest reference family, with exact vendor/revision still unverified. DFRobot's matching reference drawing distinguishes a separate 5V header from the VCC-position power output. This does not approve VCC as an input or establish safe wiring on the user's PCB.

Board-specific source links, reference supply/current figures, OV3660 driver support versus unresolved ribbon compatibility, conditional programmer requirements and the precise unpowered evidence needed are recorded in ESP32_SETUP.md under the research update. Source artifacts/hashes are preserved in data/hardware_identification.

No power, serial connection, flashing, camera initialization or JPEG work occurred during this research. The DevKit probe remains compile-only. The next physical gates remain safe electrical/programming verification, actual UART PING/PONG, then camera initialization/sensor identification, before JPEG transport.


## Photo-stage follow-up with only the DevKit available

The latest request supplied camera connector/microSD-face and separate USB DevKit photographs. A camera 5V label and matching reference header layout are visible. The camera reverse/regulator face is not supplied, so actual supply routing, regulator specifications and exact revision remain unverified. VCC is not approved as input. Only the DevKit is available; no external camera supply or dedicated programmer has been identified. DevKit VIN current capability must not be assumed.

Both UART projects now compile: the DevKit probe for esp32dev and the unchanged camera responder for a generic reference_esp32dev target only. Five simulated UART checker tests passed. COM9 now enumerates as CH9102; no port was opened. Existing original-flash and tested telemetry binary hashes match their prior records, and all three firmware sources remain unchanged. Results are in data/hardware_identification/photo_stage_findings.json and the associated build/test/preservation logs.

No board was flashed or asked to receive a new power connection. The DevKit-only camera programming route still needs a separately implemented/tested transparent bridge and verified camera boot/reset controls. An external regulated 5V source with 1A headroom is the provisional supply plan once the input is verified; a separate 3.3V-logic programmer is an optional alternative, not existing hardware.

Exact compile/simulation commands, expected future PING/PONG output and the blocked camera-initialization stage are documented in ESP32_SETUP.md. JPEG and the laptop AI pipeline were unchanged.


## 1. Original VLM disablement

config.yaml and prior --no-vlm commands disabled the experimental VLM. Main-environment Transformers 5.17 was incompatible with the cached Florence remote implementation. Its adapter also had weak accuracy, so readiness and confidence could not be assumed. The existing Transformers 4.49 / PEFT 0.14 overlay now runs Florence in a managed child process, preserving the main environment and adapter.

## 2. Previous LLM implementation

The prior assistant was an optional Ollama HTTP wrapper, not a verified direct Hugging Face production implementation. Its source and other pre-change files were preserved under data/backups/before_local_ai. It has been replaced with direct local Transformers inference. No Ollama, paid API or external inference server is used.

## 3. Selected local LLM

HuggingFaceTB/SmolLM2-135M-Instruct suits this CPU-only laptop's approximately16 GB total RAM and roughly3.5 GB free at inspection. The downloaded safetensors file is269,060,552 bytes. Float32 parameters alone require approximately0.54 GB, excluding activations, tokenizer and runtime overhead. The existing environment is retained; each model process uses two CPU threads by default. No quantization package was introduced.

Weights were downloaded once through an explicit approved setup operation. Runtime uses offline/local_files_only loading and never silently downloads or sends event/image content to a hosted service. Model card: https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct.

## 4. Actual local LLM inference

Yes. An initial real-weight unconstrained run produced unusable selection JSON; validation rejected it and returned stored facts. The final constrained integrated run generated10 tokens selecting an allowed event ID, returned generation_status=validated and llm_used=true, and exposed source IDs/evidence links in the dashboard.

This small model assists retrieved-record ordering. SQL fields supply factual answer text. It is not a verified free-form summarizer or general reasoning assistant. Constrained decoding and strict ID validation prevent generated references outside the retrieved set; semantic relevance quality has not been benchmarked.

## 5. Actual Florence inference

Yes. microsoft/Florence-2-base-ft loaded with backend/vlm/models/sentinel-vqa-v1/best. A saved event keyframe received raw "yes" to "Is a person visible in the image?", persisted with adapter_loaded=true, prompt/model/time and status=inconclusive. Numeric visual confidence remains null. Temporal loitering comes from tracking history, never that still-image response.

Both workers loaded asynchronously: VLM ready at12.11s, both ready at13.12s. Frames progressed113->153 while real QA ran; concurrent health requests took approximately2..8.4ms in this particular test. These measurements do not guarantee throughput on other workloads.

Historical VQA accuracy remains base22/40 (55%), adapter23/40 (57.5%), versus always-yes24/40 (60%). UNKNOWN abstention failed0/3 correct for both. Duplicate-image split leakage is documented; no improved field accuracy is claimed.

## 6. Files changed and purpose

| Files / directories | Purpose |
|---|---|
| backend/ai_runtime/process.py, worker.py, manager.py | Managed cached-only workers, truthful lifecycle, bounded inference and event queue |
| backend/llm/assistant.py | Direct local extractive QA, strict reference validation, recorded-fact fallback |
| backend/retrival/questions.py, retrival.py | Deterministic question/time/type/ID filters before model use |
| backend/database/event_database.py | Additive VLM metadata and parameterized event retrieval |
| backend/config/settings.py, config.yaml, backend/main.py | Independent model flags, resource limits, background integration and source/component status |
| backend/api/__init__.py, routes.py | Owned/shared resource lifecycle, models endpoint, QA and saved-evidence verification |
| dashboard/ | Preserved visual theme; real statuses, QA progress/sources and saved-keyframe checks |
| backend/camera/camera.py | Bounded network opening/reads; explicit source selection |
| scripts/download_llm.py, requirements-vlm-compat.txt | Explicit cache setup and pinned existing VLM overlay |
| scripts/smoke_local_models.py, verify_local_ai.py, check_camera_source.py | Separate real-model/browser/source integration checks |
| tests/test_local_ai.py | Mocked lifecycle, retrieval, QA, API, queue and resource-limit regressions |
| esp32/uart_probe/ | Separate compiled DevKit UART2 diagnostic; original firmware preserved |
| esp32/camera_uart_probe/ | UART0 responder compiled for a generic reference target; no camera/JPEG configuration |
| scripts/check_camera_uart.py, tests/test_camera_uart_probe.py | Future host PING/PONG checker and simulated safety/nonce/timeout tests |
| docs/, README.md, .gitignore | Setup, current evidence, hardware gates, limitations and build-output exclusions |

Earlier core fixes to tracking/state/events/evidence/API and their tests remain preserved. Existing dirty/untracked user work was not reset or removed. The old generic telemetry sketch and flash backup remain intact. The previously prepared guarded HTTP-camera template is unused and unverified; it is not the selected UART path.

## 7. Exact PowerShell launch commands

Use the existing .venv, with the wired hardware assembly unpowered until its supply is verified:
```powershell
Set-Location D:\SentinelAI
& .\.venv\Scripts\python.exe scripts/download_llm.py
& .\.venv\Scripts\python.exe -m backend.main --config config.yaml --source 0 --vlm --llm
```

Other independent model combinations:
```powershell
& .\.venv\Scripts\python.exe -m backend.main --source 0 --vlm --no-llm
& .\.venv\Scripts\python.exe -m backend.main --source 0 --no-vlm --llm
& .\.venv\Scripts\python.exe -m backend.main --source 0 --no-vlm --no-llm
```

For a controlled replay replace --source 0 with --source data/demo/still_image_fixture.avi and add --loop --no-display --max-seconds 90, preserving spaces between option names and values. This repeats a real photo and is not natural video or camera-board input. Open http://localhost:8000 while running. CLI flags independently override YAML; default YAML keeps both models opt-in.

Full dependency/cache/environment instructions and bounded verification commands are in LOCAL_MODELS_SETUP.md. SENTINEL_CONFIG selects a configuration; SENTINEL_LLM_MODEL selects an already cached alternate model. No API credential is required.

## 8. API and dashboard checks

Wait for actual ready states, not merely enabled flags:
```powershell
Invoke-RestMethod http://localhost:8000/api/models
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/events
Invoke-RestMethod -Method Post http://localhost:8000/api/llm/query -ContentType 'application/json' -Body '{"question":"When was the latest loitering event?"}'
```

Use a real returned event ID with saved evidence:
```powershell
$eventId = 51 # example from the recorded run; replace with an actual current ID
Invoke-RestMethod -Method Post "http://localhost:8000/api/events/$eventId/verify"
Invoke-RestMethod "http://localhost:8000/api/events/$eventId"
```

Verification returns202 when queued; poll until its status changes. Inspect vlm_prompt, vlm_model_id, vlm_raw_text, vlm_adapter, vlm_checked_at and any error. No record/image -> explicit failure; disabled/loading/error -> honest state.

Dashboard: http://localhost:8000. Check VLM/LLM and camera/YOLO/tracker/database states; open an evidence thumbnail; select "Check saved keyframe"; ask "What events occurred in the last five minutes?", "When was the latest loitering event?" or "Which events have VLM verification results?". Use a timezone-qualified ISO time for around-time queries. Answers cite stored event IDs and evidence. No matching record means no matching evidence, not proof of absence.

Actual integration evidence: data/integration/end_to_end.json and dashboard_local_ai.png. The browser run had no JavaScript errors. A later source-ordering fix was covered by regression tests; screenshot predates the CSS scroll-height refinement.

## 9. Hardware identification and programming status

DevKit: historical physical query verified ESP32-D0WD rev1,4 MB, onboard CH9102 USB-UART, COM9. Exact vendor PCB is unspecified. The current source uses USB Serial only; it does not start UART2 and is not a programming bridge.

Camera PCB: user reports ESP-32S, microSD, FPC, GPIO headers, no USB. Ribbon now reported inserted, apparent code TY-OV3660-2.1M-V3. Exact PCB/sensor compatibility, FPC orientation, supply pin/voltage/current, UART header routing and boot/reset/programming controls remain unknown.

Required next evidence: readable front/back PCB photos, all header labels, regulator markings, board model/revision, ribbon/sensor codes and FPC contacts/latch; matching seller schematic if available. Earlier identification had no board photos; the latest follow-up includes the camera connector face and DevKit face, with the camera reverse/regulator view still missing. MicroSD is optional; laptop SQLite/evidence storage remains the target.

UART0 is commonly the ESP32 download/console port. A runtime responder must reserve it, distinguish boot logs and avoid console output. A DevKit could support transparent programming or runtime relay with suitable firmware and verified boot/reset controls, but neither the original JSON firmware nor the diagnostic probe is a programming bridge. No camera flashing command or boot-pin short is justified yet.

## 10. Connection-by-connection table

| Component / connection | Current status | Flashing versus runtime |
|---|---|---|
| Laptop USB -> DevKit micro-USB | Previously physically worked; user now reports connected; keep disconnected while camera is unpowered and wired | DevKit programming and eventual USB runtime |
| DevKit GND -> camera GND | User-reported connected, not continuity-verified | Shared UART reference after verification |
| DevKit TX2/GPIO17 -> camera U0R/U0RX | User-reported connected; current telemetry source does not enable it | Intended camera RX; header routing still requires verification |
| DevKit RX2/GPIO16 <- camera U0T/U0TX | User-reported connected; no physical exchange tested | Intended camera TX; header routing still requires verification |
| Supply -> camera power pin | No confirmed connection; pin/voltage/current unknown | Required before any powered camera test; no voltage prescribed |
| Camera ribbon -> FPC | Reported inserted; compatibility/orientation unverified | Needed for later image capture; disconnect all power before handling |
| Camera boot/EN controls | Mapping/programmer unknown; no wire/short instruction | Needed to enter download mode/reset; runtime normally leaves boot mode |
| microSD | Optional, no storage dependency | Not needed for initial demo |

No existing signal-wire change is requested. DevKit USB power removal has a specific reason: driven UART TX can back-feed the unpowered camera via protection paths. Do not infer5 V input from VCC. Exact supply wiring cannot be supplied until reliable board-specific evidence exists.

The new DevKit project explicitly uses Serial2.begin(115200,SERIAL_8N1,16,17), but only after an explicit power-verified enable command. It starts GPIO16/17 as inputs, has a two-second nonce-matched PING/PONG timeout, and transfers no images. Compilation passed; neither board was flashed and no active probe was run.

## 11. Physical camera frame provenance

No. No camera-origin frame or real camera UART PING/PONG has been verified. Latest integrated run selected data/demo/still_image_fixture.avi, with source_kind=video_file and esp32_camera_verified=false. Earlier live frames came from the laptop webcam. COM9 was absent in the integrated run; later user-reported USB presence does not establish serial operation, power or frames.

Required sequence: establish board-specific safe power and UART routing -> identify camera programmer/boot controls -> flash appropriate UART probe firmware -> verify a fresh physical PING/PONG -> verify camera initialization and sensor PID -> only then implement framed JPEG transport and host decoding -> prove live camera provenance by changing a target at that camera, with webcam excluded, and interrupting that source. Do not substitute compilation or a displayed fixture for any hardware stage.

## 12. Verification and remaining limitations

Final focused tests:116 passed, one upstream Starlette/httpx deprecation warning. Ordinary tests use mocked models/serial, never load heavyweight weights or assert hardware success. DevKit UART probe compile succeeded:22,260 bytes static RAM and299,380 bytes firmware. Real local-model/browser results were obtained separately from unit tests.

Final logs: data/integration/final_pytest.log, final_compile.log, final_dependencies.log, final_whitespace.log, uart_probe_build.log. Real model lifecycle/API/UI artifacts: end_to_end.json, dashboard_local_ai.png. Initial standalone model result: local_models.json, including the pre-constrained LLM fallback.

No further dependency is missing for the verified software demo. Main-environment Florence incompatibility is handled by the existing pinned overlay, not a global downgrade. CPU contention, bounded queues, model timeouts, small-model ranking quality and historical timestamps without timezone offsets remain limitations. Existing naive timestamps were not silently reinterpreted or rewritten.

The hardware path is blocked on identification and electrical/programming verification, not finished. No UART JPEG implementation was attempted after the user's explicit stage order. No camera power, camera flash or signal change was performed. See ESP32_SETUP.md and KNOWN_LIMITATIONS.md for practical gates and limits.


## 13. Presentation readiness update - 20 October 2026

This update supersedes older test totals and checker defaults above. The laptop pipeline, detector, tracking, event rules, database, API, dashboard and optional local AI implementations were preserved. Changes are confined to diagnostics, temporary UART-probe safety, bridge error reporting, tests, presentation configuration and documentation.

**A. Automated software verification:** 161 regression tests passed, with one upstream Starlette deprecation warning; 50 are software-only camera/bridge simulations. All four firmware projects built successfully (telemetry, DevKit probe, generic reference camera responder, temporary bridge). UART probe build: RAM22,268 / flash299,616 bytes. Camera responder: RAM22,140 / flash288,620. Bridge: RAM22,676 / flash295,560. Compilation establishes neither physical target identity nor successful programming. Full output: `data/presentation/pytest.log`, `build_results.json` and its four logs.

A new saved-webcam replay processed30 frames with tracks on all30, persisted one PERSON_ENTERED event and its JPEG evidence, and exited cleanly. A second, looped recorded-video dashboard check passed in headless Edge: 640-pixel preview,94 WebSocket messages, REST frame/evidence responses, no JavaScript errors, clean application exit. The isolated presentation database accumulates entry events when segments rewind; these are replay events, not a measurement of real arrivals. Source was `data/demo/webcam.avi`, not an ESP32 camera. ESP32 serial was disabled in configuration and serial construction was independently forbidden inside the browser-test child. Optional VLM/LLM were disabled in these runs; their earlier physical laptop/software model evaluation results are unchanged and were not repeated.

**B. Hardware operations actually performed:** none in this run. COM9 was never opened, no physical UART transmission or flash/readback/erase/reset was attempted, no boot settings or wires were changed, and no power was applied by the agent. User-reported present power state is unmeasured. File copies, source compilation, fake serial tests and recorded-video inference are software operations.

The exact tested telemetry application, source, PlatformIO configuration, bootloader, partition table and earlier full-flash backup remain hash-matched. Recovery copies are referenced by `data/presentation/recovery_location.json`; validation is `preservation_after.json`. A rebuild produced a different app binary, retained separately as `rebuilt_telemetry.bin`; the original tested firmware.bin was restored. Disk recovery artifacts are not a newly verified recovery procedure or a current full-flash snapshot.

**C. Hardware not verified:** exact camera PCB/sensor revision; labelled5V and1117-family regulator routing; second DevKit/power-bank supply voltage/current/protection budget; UART0/IO0/reset routes and download controls; either probe or bridge installed on a board; ROM synchronization; real camera PING/PONG; sensor initialization/PID; frame capture. Historical primary telemetry records can be inspected without serial and are explicitly labelled historical evidence. A checker timeout does not diagnose defective hardware.

**D. Shortest remaining path:** obtain one qualified unpowered net-map inspection covering power/UART/IO0/reset and establish one verified supply/current budget, including the second DevKit's actual rail. Then, with explicit authorization and recoverable flash snapshots, validate a temporary bridge and manual target ROM-mode/reset controls, establish ROM communication, install the UART responder and run the primary probe for a fresh nonce-matched PING/PONG with acknowledged shutdown. Using the second DevKit as a temporary programmer could preserve the primary's telemetry, but requires separately verified UART routing and intentional wire changes; that route is not currently established. After physical UART passes, verify camera mapping/sensor compatibility and implement/run initialization/PID diagnostics. JPEG transfer and host ingestion remain gated on those physical results. No separate programmer is proven necessary if the existing bridge and manual controls can be physically validated; a meter/technician and a verified power source may still be necessary.

Exact safe PowerShell presentation, checker and build commands are at the top of `docs/ESP32_SETUP.md` and `docs/DEMO_GUIDE.md`. `config.presentation.yaml` disables ESP32 serial, uses a separate database/evidence directory and serves the dashboard at http://127.0.0.1:8010. The camera checker and telemetry checker are inert by default. No command declaring verified power/firmware was executed against hardware.


## Real-time ESP32 source preparation follow-up

The new requested ESP32 feed remains physically blocked. No new electrical/sensor identification evidence arrived, and the active camera firmware is still only a PING/PONG responder. Genuine sensor capture firmware is conditional on an established target/programming route and was not implemented using a guessed board map. The existing primary telemetry and camera responder source/binaries remain preserved; no serial/flash/reset/power/wiring action was performed.

Host-side implementation now includes a proposed bounded/checksummed SNC1 packet decoder, sensor-status/session/sequence validation, dimension-checked JPEG decoding, a one-frame background receiver with reconnect/drop/timeout metrics, explicit gated ESP32 source selection, received-time/session/frame provenance persisted with events, dashboard transport details and a single conservative diagnostics command. Missing physical approval or fresh live evidence blocks the launcher before model/device startup. Simulation/replay cannot supply live approval.

201 automated tests passed (28 new software stream/source tests), and all four existing firmware builds passed. A real recorded-video fallback check passed actual detector/events/storage/REST/WebSocket/browser/persistence with source provenance still video_file and ESP32 verification false. Optional models were not re-evaluated in this fallback check; normal presentation defaults continue enabling both. No camera PID, JPEG, continuous ESP32 video, ESP32-origin model inference or physical camera performance was verified. Exact commands, protocol boundaries, current results and the one next physical inspection item are at the top of ESP32_SETUP.md.


## Three-board power-only secondary and capture-core update

The reported power path is now explicit: USB power bank -> secondary DevKit USB -> secondary5V/GND -> camera5V/GND. Primary USB/COM9 and GPIO17/16/GND provide data. No primary positive power tie is reported. This clarifies roles, not the measured electrical limits. Reference manufacturer documentation cannot establish the actual secondary's spare5V output capacity or this camera's power/pin-map/sensor identity.

An offline `esp32/camera_capture` driver core now calls initialization/PID/frame acquisition APIs and emits the receiver's framed JPEG/status protocol, with one-buffer/cap/deadline/release/error handling and framed fresh-nonce PONG responses. The included generic reference entry point is inert; no hardware pin map or production camera image is supplied. A gated runtime controller reuses the unchanged primary binary bridge in normal camera boot, suspends legacy telemetry during raw transport, checks a fresh camera PONG and uses acknowledged shutdown. Its30-second silence /15-minute session /about32-second cleanup constraints remain explicit. Primary telemetry source/binary and backup were preserved; no MCU was flashed or reset.

210 regression tests and five compile-only builds passed (four existing targets plus the inert capture reference). OS-only enumeration found COM9 without opening it. No camera response, PID, JPEG, continuous camera video or model inference on ESP32-origin frames was physically verified; camera FPS/resolution/stability remain unmeasured. The six-stage diagnostic and exact safe commands are documented at the top of ESP32_SETUP.md. Existing successful laptop/model tests were not repeated as substitute camera evidence.
