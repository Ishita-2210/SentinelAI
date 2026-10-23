> Historical validation and setup notes. For this release pass, see [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md), [AI_MODELS.md](AI_MODELS.md) and the authoritative [hardware guide](HARDWARE_SETUP.md).

# Final engineering validation - 20 October 2026

The official presentation uses the laptop webcam with both local models:

```powershell
Set-Location D:\SentinelAI
& D:\SentinelAI\scripts\run_presentation.ps1 -Source 0
```

Open http://127.0.0.1:8010. Stop with Ctrl+C. The zero-argument launcher also selects webcam 0. Explicit ESP32 remains gated and experimental. No physical serial, flashing, reset, power or wiring operation was performed during this pass.

## Fresh results

| Check | Actual result |
| --- | --- |
| Initial regression baseline | 246 passed, zero failures |
| Final regression suite | 266 passed, zero failures; 1 existing deprecation warning; synthetic images/records and mocked inference/serial |
| Dependency consistency | `pip check`: no broken requirements |
| Python syntax | `compileall -q backend scripts`: passed |
| Presentation preflight | `run_presentation.ps1 -Source 0 -Check`: passed; both models enabled; serial disabled |
| Actual full-AI webcam application | Bounded 180-second run, clean exit; 61 fresh events (IDs 414-474), all 61 referenced JPEGs exist |
| Actual webcam browser verification | Passed; changing real webcam frames; REST events/evidence; fresh adapter Florence output; real SmolLM2 QA; 30 WebSocket messages; zero browser JavaScript errors |
| Responsiveness during browser QA | Processed-frame count advanced from 265 to 283; this is an observation, not an FPS benchmark |
| Preview failure/recovery | Deliberately intercepted browser image requests; stale image hid, then recovered after requests resumed |
| Actual local adapter model smoke | Passed: Florence returned `yes` for still-image person presence; SmolLM2 returned a validated retrieved-ID selection |
| Actual base Florence evaluation | Passed: `<DETAILED_CAPTION>` parsed into readable scene observations; normalized presence remained `unknown`; task and exact JPEG SHA-256 persisted |
| Actual grounding cases | Four genuine SmolLM2 generations: valid record, missing image reference, conflicting/error metadata, unavailable identity/intent; supplied-ID validation and explicit uncertainty passed |
| Actual model recovery | Corrupt JPEG intentionally failed; a valid image then succeeded in the same loaded Florence worker. Final evaluation counters: 2 successful VLM requests and 4 successful LLM requests |
| Empty retrieval | Explicit no-evidence answer, with no inference call |
| ESP32 software checks | Inert checker: blocked, `serial_opened=false`; software fixtures do not establish physical camera operation |
| Firmware compilation | Five builds passed: telemetry, UART probe, camera UART responder, programmer bridge, inert camera capture reference |
| Cleanup | Bounded webcam run returned 0; no matching backend/presentation/model worker processes remained; port 8010 had no listener |
| Post-integration recorded-video smoke | Full-AI flags retained; bounded 8-second run used `data/demo/webcam.avi`, ran actual YOLO/ByteTrack, saved one new event/JPEG, and exited 0. This short check does not claim model inference completed |

The base caption described visible people, a phone and room objects. Its statements were not independently adjudicated for accuracy; demographic descriptions and other generated details remain unverified model output. The adapter answer is also uncalibrated. Neither run proves dwell, intent, ownership, running or other temporal events.

## Improvements and their evidence

| Stage | Defect or boundary addressed | Validation |
| --- | --- | --- |
| Acquisition | Reopening could retain a capture; malformed successful reads could reach inference | Release before reopening; image validation; existing camera failure/timeout tests |
| YOLO11n / ByteTrack | Invalid frame input and empty detect-only results were not guarded | Early BGR uint8 validation and empty-result handling; regression tests and genuine webcam tracks; weights/thresholds unchanged |
| Tracking / deterministic rules | Retired state and event dictionaries accumulated IDs | Expire long-retired histories while retaining brief losses and still-linked owners; regression checks for memory expiration and existing temporal behavior |
| Evidence / SQLite | Same timestamp/type/track could overwrite a JPEG; shared-connection reads were unsynchronized; legacy range query compared timezone strings | Unique evidence filenames, filename validation, serialized reads, normalized date comparisons; persistence and provenance tests |
| Florence | Base model received an adapter-specific question and a four-token answer budget | Preserve adapter prompts; use supported base caption task and parsed result; mock task/parsing tests plus genuine base and adapter inference |
| Association / orchestration | Image replacement or changed event evidence could invalidate results; one bad image marked a healthy model unavailable | Queued image digest, exact-byte worker check, event association checks, successful-result deduplication, retryable request errors; provenance/mock tests and genuine corrupt-image recovery |
| SmolLM2 | Silent truncation could cut records/question; missing and visual context were underspecified | Whole-record reduction, bounded unverified visual context and explicit evidence availability, supplied-ID-only response validation; mock contracts and four real generations |
| Dashboard / API | Base captions needed an accurate display; preview/source/error state needed to remain truthful | Separate unverified-caption presentation, webcam label/default, preserved stale-preview and disconnect behavior; actual Edge/browser/API/WebSocket run |

The application keeps deterministic event occurrence separate from AI output. SmolLM2 remains an extractive source selector; factual prose is rendered from SQLite. Increasing narrative freedom was not justified for this small model. No replacement model, paid API, weight changes, threshold tuning, detector-accuracy claims or fabricated performance gains were introduced.

## Reproduce

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m compileall -q backend scripts
& .\scripts\run_presentation.ps1 -Source 0 -Check

# Terminal 1: full-AI webcam application
& .\scripts\run_presentation.ps1 -Source 0 -MaxSeconds 180
# Terminal 2: attaches to the running application, requires visible events
& .\.venv\Scripts\python.exe scripts/verify_presentation.py --expected-source webcam

# Separate model contract evaluation, using an authorized saved image:
& .\.venv\Scripts\python.exe scripts/evaluate_ai_grounding.py --base --image 'C:\path\to\keyframe.jpg'
# Omit --base to evaluate the configured optional adapter instead.
```

`tests/test_pipeline_grounding.py` adds synthetic/mock checks for invalid images, BGR conversion, file ownership, both Florence modes, malformed output, model exceptions, unique evidence, wrong-event images, provenance retrieval, bounded QA context, missing/conflicting evidence, context overflow, temporal-memory cleanup and webcam defaults. Existing tests cover event rules, model IPC lifecycle, invalid generated references, REST, WebSocket disconnects, serial protocol fixtures and hardware gates. These tests check contracts, not subjective reasoning quality.

Ordinary unit runs do not load weights or access hardware. The separate evaluation script loads installed local models and uses synthetic SQLite records in a temporary database, paired with an explicitly supplied real image. Synthetic LOITERING metadata is not a physical incident. The malformed-model-response cases use mocks; real corrupt-image recovery uses the actual worker. `smoke_local_models.py` separately reused historical saved evidence and real weights; its event timestamps were not new live observations.

The firmware commands in the README compile only. The camera capture build is deliberately inert and does not select an approved physical pin map. Telemetry source SHA-256 stayed:

```text
06A991B5418B69D46FB68B62EF3F59A25F8BE14B41CADD050B8B2B4402063FF2
```

Recovery copies and existing firmware were retained. Build artifacts, logs, evaluation databases, event data, screenshots and model caches remain ignored and are not committed.

## Limitations and failures encountered

An intermediate regression run had 244 passing tests and two failures: a test still asserted the superseded ESP32 default, and a dtype test mocked a base model while expecting an adapter answer. The first now explicitly tests gated ESP32 selection; the second explicitly mocks adapter mode, with separate base-task assertions added. No failing test was removed or assertion weakened to hide a defect.

The final suite retains one existing Starlette/httpx test-client deprecation warning. The installed Florence compatibility stack also logs adapter-version/generation-setting warnings; actual loading and inference succeeded. No dependency upgrade was attempted during presentation finalization. A deliberate corrupt-image exception in worker logs is expected evaluation evidence.

Hardware field accuracy, false-positive rates, tracking accuracy, latency and FPS improvements were not measured. Webcam acquisition and YOLO remain synchronous; slow AI is isolated in workers. There is no automatic evidence retention, authentication for public hosting, or general semantic database search. IDs may change after loss; repeated-video entries are replay events. Tests do not make ESP32 hardware presentation-ready.

**ESP32 camera integration is experimental. Physical sensor initialization, firmware flashing, genuine JPEG reception, continuous video, dashboard display, and AI processing of real ESP32-origin frames have not been verified end to end.**

## Local Git integration note

The initial branch was `feature/sentinelai-complete`; local `main` was its ancestor. The reviewed implementation was committed and fast-forwarded into local `main`, preserving the feature history. No remote was changed. Local main and the existing `origin/main` reference diverge; remote reconciliation was outside this local-commit task.

During the branch switch/fast-forward, Git removed legacy files that older main tracked and the feature commit had untracked: `yolo11n.pt`, `data/sentinelai.db` and `.gitgnore`. These were restored locally from the preserved Git objects and remain ignored. The restored YOLO Git blob matches `45b273b46165267f2d4c90df94468b547f43cf67`; presentation preflight and the recorded-video detector smoke passed afterward. The legacy database was restored from its historical Git snapshot; its pre-switch ignored bytes were not independently captured, so equivalence to that previous local copy cannot be guaranteed. The presentation database/evidence and demo/evaluation directories were unaffected. No model weights or database were added to the final commits.
