# Known limitations

- The requested camera -> UART -> DevKit -> SentinelAI path is unfinished. Camera supply pin/voltage/current, exact board, sensor compatibility, header routing and programming controls remain unverified. Signal wires are user-reported; no physical PING/PONG or camera frames have been tested. The separately compiled DevKit probe has not been flashed.
- Prior physical DevKit tests cover USB telemetry/ping/alert only. COM9 was absent during the latest integrated model run; the later USB-connected report has not been electrically/serially checked after the wiring disclosure.
- No representative held-out detection annotations or long natural-video event benchmark is available. Detector mAP, field event F1 and tracking IDF1/HOTA are unmeasured. A 30-frame webcam clip demonstrates operation, not broad accuracy.
- The repeated-photo fixture is synthetic temporal input. Its real inference/persistence/UI path does not establish natural motion, ownership or dwell accuracy. Rewinds reset state; repeated runs append records.
- RUNNING is image-plane rapid motion, and unattended ownership is proximity-based. Perspective, occlusion and ID fragmentation can affect events. An inferred exit after disappearance is not proof of departure.
- Florence adapter scored 23/40 versus base 22/40 and always-yes 24/40. Both models failed all three UNKNOWN cases. Cross-split image duplicates contaminate the full-test score. No accuracy improvement or calibrated confidence is claimed.
- Florence now runs through the verified Transformers 4.49 overlay. It can load/infer with the adapter, but every result remains an inconclusive still-image presence hypothesis, separate from temporal events.
- Direct local SmolLM2-135M is intentionally small for CPU/RAM limits. Unrestricted generation failed schema validation; constrained event-ID generation was verified. Factual text is rendered from retrieved SQLite rows, not model-authored summaries. Semantic ranking quality is unmeasured.
- Question parsing supports a bounded set of intents, not arbitrary language or SQL. Retrieved results are capped; absence of matching records is not proof nothing happened. Old timestamps without timezone offsets are interpreted by SQLite as UTC, which may be ambiguous; historical records were not silently rewritten.
- Models are opt-in, cached-only and run in separate managed processes. Concurrent CPU load affects FPS; queue capacity, busy/timeout errors and memory limits still apply. There is no throughput guarantee.
- API dependencies are process-wide; multiple application workers are unsupported. Standalone API serves saved history but does not start detection.
- VLM metadata stores the latest check, not an immutable audit history. Missing evidence, queue overflow and cancelled checks remain explicit. Evidence-write failure can leave an event without an image.
- Device uptime is not a synchronized wall clock. No physical actuator or safety-critical response is implemented.
