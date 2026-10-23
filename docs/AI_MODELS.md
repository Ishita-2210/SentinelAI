# AI model setup and interpretation

Use the tested installation and explicit first-time downloads in the [README](../README.md). The [detailed model notes](LOCAL_MODELS_SETUP.md) preserve implementation history and experiments. No Ollama, cloud inference key or separately running inference service is required: the host starts two local Python subprocesses.

| Model | Input and real task | Output and limitations |
| --- | --- | --- |
| YOLO11n + ByteTrack | Selected video source, one tracking invocation per frame | Detector boxes/confidences and persistent track IDs. IDs are not identities. Representative field accuracy is unmeasured. |
| Florence-2-base-ft | Actual saved event image. Optional trained adapter: presence VQA; base model: `<DETAILED_CAPTION>`. | Original text, task, prompt, model ID, evidence hash and state. All successful visual results remain `inconclusive`; no calibrated confidence is invented. Still images cannot verify time, ownership or intent. |
| SmolLM2-135M-Instruct | Bounded SQLite records or an actual Florence caption, plus a question | Written prose labelled as interpretation, or the preserved constrained source-ID/recorded-facts mode. The model cannot directly see pixels; source links are supplied by the host. |

The managed workers currently use CPU float32; `detector.device` can choose the YOLO device. The legacy `vlm.device` field does not switch the managed worker to GPU. Do not infer GPU support from that field. Florence's pinned Transformers 4.49 overlay is isolated under `data/evaluation/vlm_runtime`; SmolLM2 uses the main environment. Keep dependencies pinned unless compatibility is tested.

Model weights and adapters are excluded. The optional adapter may be absent on a fresh clone; set `vlm.adapter_dir: null` for explicit base mode. Missing requested adapters expose a warning when base fallback succeeds. All workers load cached files offline. Missing cache/dependencies produce visible errors while event ingestion continues.

## Runtime states and recovery

`disabled` means intentionally off; `loading` means initialization underway; `ready` means weights loaded. `busy` identifies an active request. Completed-inference counters and last inference duration only change after a real successful worker response. A package import alone never establishes readiness. Loading and inference limits terminate a stalled model worker; restart the application after correcting the underlying cause. A bad image can retry in the same healthy worker.

Each model permits one active request. Florence uses a bounded priority queue with pending-ID deduplication. Event states distinguish `queued`, `processing`, `inconclusive`, `error`, `skipped` and `cancelled`. Saved per-event duration includes model-readiness wait when applicable, unlike the last successful model request duration. Old records without timing retain null values. Shutdown cancels unfinished queued/processing records.

In the dashboard, **Inspect event** shows the original keyframe, decoded image dimensions, source metadata, actual Florence task/output and hash. **Analyze saved keyframe** queues genuine inference; errors remain visible. **Ask about event** fills a supported event-ID question. LLM answers show actual model use versus a recorded-fact fallback, elapsed successful inference and clickable event/evidence references. No records means no inference and an explicit evidence limitation.

Unit tests mock models and prove contracts only. Run [release verification](../scripts/verify_release.py) explicitly with an authorized local video for real weights, API and browser checks. Generated screenshots/reports remain ignored and private. Review [fresh release validation](RELEASE_VALIDATION.md) for what actually ran.

## Written frame descriptions

The dashboard now shows two paragraphs beneath the live preview: a genuine Florence image description and a local LLM explanation of that description. **Describe current frame** captures the actual current annotated preview with its sequence, source, SHA-256 and timestamp. `POST /api/scene` enqueues it in the existing bounded VLM queue; `GET /api/scene` exposes queued/describing/explaining/completed/error states. Repeated requests share the active analysis rather than starting parallel model copies. A stale/missing preview is rejected.

Captioning explicitly uses `<DETAILED_CAPTION>` even when the yes/no LoRA adapter is loaded. The adapter is temporarily bypassed in a context manager and restored afterward; its normal event-verification behavior remains available. Scene captions and event presence checks share the same loaded Florence worker. The LLM then generates prose from that caption; if unavailable, the UI labels its fallback as the supplied visual description rather than pretending language inference succeeded.

Automatic analysis is enabled every 30 seconds in the dashboard and can be unticked. One scene job is active at a time. Snapshot JPEGs remain under the configured evidence directory; the latest caption/explanation state is held in memory and resets on restart. No detection event is fabricated for a manually requested snapshot. There is no automatic deletion; monitor local disk use. Descriptions apply to their linked snapshot, not continuously to the changing live feed.

For event questions, `POST /api/llm/query` accepts `mode: explain` for written interpretation or `mode: facts` for the preserved factual source-selection path (the API default for compatibility). Unsupported references, empty/JSON-only prose and model errors return an explicit fallback. Source references reflect the records retained within the model's context budget. Generated prose is not a calibrated factual verification or a general investigative tool.
