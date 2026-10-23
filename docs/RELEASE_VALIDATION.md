# Release validation — 23 October 2026

This report records this release pass, separately from the preserved 20 October reports. Initial Git state: clean `main`, `origin` already targeting `Ishita-2210/SentinelAI`, HEAD `ccd1f78`. No existing uncommitted user work was replaced. Git history and remote configuration are preserved.

## Changes covered

- Responsive vanilla dashboard with local system fonts, refined contrast, native keyboard-accessible event dialog, evidence dimensions/provenance, actual Florence tasks/output and clickable LLM event references.
- Escaped untrusted text/attributes and encoded evidence filenames; no generated executable HTML handlers.
- One coalesced latest WebSocket frame, bounded 64-notification queue, bounded concurrent client sends and failed-client cleanup. REST/SQLite remains authoritative for displaced updates.
- Explicit VLM processing state, additive per-event duration migration, successful model-request timing and cancellation of unfinished processing records.
- Authoritative hardware guide and diagram, preserved historical wiring accounts, clearer model/development/security documentation and local publication scanner.

## Automated and build results

| Check | Result |
| --- | --- |
| Baseline regression suite | **266 passed**, one existing FastAPI/Starlette `httpx` deprecation warning |
| Expanded regression suite | **277 passed**, same warning; no tests deleted or assertions weakened |
| New coverage | Slow/failed client isolation, 10,000-frame coalescing, bounded notifications, VLM processing/duration/cancellation, publication secret/artifact checks, actual staged-blob scanning |
| Python parsing/compilation | All 78 backend/script modules parsed; `compileall` passed for backend, scripts and tests |
| Browser JavaScript syntax | `node --check dashboard/dashboard.js` passed |
| Dependency consistency | `pip check`: no broken requirements |
| Firmware: telemetry | Passed; RAM 22,244 bytes, application 293,616 bytes |
| Firmware: UART probe | Passed; RAM 22,268 bytes, application 299,616 bytes |
| Firmware: camera UART responder reference | Passed; RAM 22,140 bytes, application 288,620 bytes |
| Firmware: programming bridge | Passed; RAM 22,676 bytes, application 295,560 bytes |
| Firmware: inert camera capture reference | Passed; RAM 22,108 bytes, application 268,932 bytes |

All firmware commands were compile-only. The separate AI-Thinker first-JPEG hypothesis was **not built or tested in this pass** because its physical GPIO map remains unconfirmed. No firmware source was changed or uploaded. Compiled outputs stay ignored.

Ordinary tests use synthetic frames and mocked model/serial responses. They establish software contracts, not model accuracy or physical hardware behavior. An early new scanner test mistakenly treated generic fixture words as leaked values; its fixture content was corrected before the passing regression run.

## Genuine local models and browser flow

Command run with cached real weights:

```powershell
& .\.venv\Scripts\python.exe scripts/verify_release.py --source data/demo/still_image_fixture.avi --base
```

This existing local input is a **repeated-photo video fixture**, not a live scene or validated real-world behavior sequence. The detector/tracker, deterministic event persistence, original keyframes and both AI workers ran for real. Verification used a new isolated database/evidence directory and localhost port, disabled serial independently of configuration, selected Florence base mode explicitly, and temporarily selected manual-only visual checks in its private verification configuration. The normal presentation configuration was unchanged.

Observed successful operations:

- Florence-2-base-ft: one manual inference, actual `<DETAILED_CAPTION>` result stored with image SHA-256, `answer=unknown`, `status=inconclusive`, measured processing duration **10,254.5 ms**.
- SmolLM2-135M-Instruct: one browser-submitted event-ID question, **9 generated tokens**, **227 input tokens**, **3,247.2 ms** request duration, `generation_status=validated`, with a reference resolving to a real record in that verification database.
- Real preview and WebSocket connection; event inspection loaded the original saved image, source links reopened event details, Escape closed the dialog, desktop 1440 px and mobile 390 px layouts passed (no horizontal document overflow).
- No browser JavaScript errors. Video processing continued during LLM inference. Final successful inference counters were Florence **1**, LLM **1**. The process exited **0** through its normal camera/model/database cleanup.

Durations are individual observations on this machine, **not performance benchmarks or guarantees**. A first verification attempt exceeded its fixed application window after model warm-up while manual work waited behind automatic checks; the application exited cleanly. The verifier was corrected to isolate the manual check and request graceful shutdown; the subsequent complete run passed. No production inference timeout was relaxed.

Separately labelled **simulated browser checks** injected hostile text, a missing evidence image and an unavailable API. All passed; those simulated responses do not count as genuine model or hardware results.

Detailed private results and screenshots are preserved locally under ignored `data/release_validation_20261023_195103_527195/`. They are excluded from the commit because they include local footage and evidence. The failed earlier report is also preserved. The repository scanner does not upload data.

## Presentation launcher and onboarding checks

`run_presentation.ps1 -Source 0 -Check` passed without opening a webcam or serial port. CLI help and the documented source/model flags were checked. The actual launcher was then run with an existing recorded webcam clip and `-MaxSeconds 12`: it served the configured localhost API, processed the recording, saved an event and exited **0**, logging normal cleanup. That bounded launcher smoke check does not establish model completion; the separate real-weight run above does.

Start the presentation from the repository root:

```powershell
& .\scripts\run_presentation.ps1 -Source 0
```

Open **http://127.0.0.1:8010**. Both AI models remain enabled. No fresh virtual environment installation was performed; installed dependencies and CLI/preflight behavior were checked. No Python linter/formatter or Mermaid renderer is configured/available; diagram source was reviewed and relative Markdown file links checked, without claiming rendered-diagram validation.

## Publication and limitations

Candidate-file secret and size scanning passed with zero findings. The largest versioned asset is an existing screenshot at **1,148,555 bytes**; no model weights, private evidence, new screenshots or runtime databases are publication candidates. The scan is heuristic; staged content also requires review. `.gitignore` preserves configuration templates and scopes runtime database exclusions, while environments, model caches, datasets, archives, logs, evidence and recovery copies remain local. No redistribution license has been selected or added.

No physical test was performed, and COM9 was not opened. Camera power/current, continuity, board/sensor identity, GPIO/reset/programming routing, initialization/PID, genuine JPEG and continuous delivery remain unverified. See [hardware setup](HARDWARE_SETUP.md). There is no authenticated public deployment, automatic retention policy, measured field accuracy or calibrated visual confidence. None is implied by passing software tests.
