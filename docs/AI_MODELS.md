# AI model setup and interpretation

Use the tested installation and explicit first-time downloads in the [README](../README.md). The [detailed model notes](LOCAL_MODELS_SETUP.md) preserve implementation history and experiments. No Ollama, cloud inference key or separately running inference service is required: the host starts two local Python subprocesses.

| Model | Input and real task | Output and limitations |
| --- | --- | --- |
| YOLO11n + ByteTrack | Selected video source, one tracking invocation per frame | Detector boxes/confidences and persistent track IDs. IDs are not identities. Representative field accuracy is unmeasured. |
| Florence-2-base-ft | Actual saved event image. Optional trained adapter: presence VQA; base model: `<DETAILED_CAPTION>`. | Original text, task, prompt, model ID, evidence hash and state. All successful visual results remain `inconclusive`; no calibrated confidence is invented. Still images cannot verify time, ownership or intent. |
| SmolLM2-135M-Instruct | Bounded SQLite event metadata, user question and available unverified visual observations | Constrained source-ID selection, then factual answer rendering by the host. Links resolve to actual event records. This is limited extractive QA, not an unconstrained investigation assistant. |

The managed workers currently use CPU float32; `detector.device` can choose the YOLO device. The legacy `vlm.device` field does not switch the managed worker to GPU. Do not infer GPU support from that field. Florence's pinned Transformers 4.49 overlay is isolated under `data/evaluation/vlm_runtime`; SmolLM2 uses the main environment. Keep dependencies pinned unless compatibility is tested.

Model weights and adapters are excluded. The optional adapter may be absent on a fresh clone; set `vlm.adapter_dir: null` for explicit base mode. Missing requested adapters expose a warning when base fallback succeeds. All workers load cached files offline. Missing cache/dependencies produce visible errors while event ingestion continues.

## Runtime states and recovery

`disabled` means intentionally off; `loading` means initialization underway; `ready` means weights loaded. `busy` identifies an active request. Completed-inference counters and last inference duration only change after a real successful worker response. A package import alone never establishes readiness. Loading and inference limits terminate a stalled model worker; restart the application after correcting the underlying cause. A bad image can retry in the same healthy worker.

Each model permits one active request. Florence uses a bounded priority queue with pending-ID deduplication. Event states distinguish `queued`, `processing`, `inconclusive`, `error`, `skipped` and `cancelled`. Saved per-event duration includes model-readiness wait when applicable, unlike the last successful model request duration. Old records without timing retain null values. Shutdown cancels unfinished queued/processing records.

In the dashboard, **Inspect event** shows the original keyframe, decoded image dimensions, source metadata, actual Florence task/output and hash. **Analyze saved keyframe** queues genuine inference; errors remain visible. **Ask about event** fills a supported event-ID question. LLM answers show actual model use versus a recorded-fact fallback, elapsed successful inference and clickable event/evidence references. No records means no inference and an explicit evidence limitation.

Unit tests mock models and prove contracts only. Run [release verification](../scripts/verify_release.py) explicitly with an authorized local video for real weights, API and browser checks. Generated screenshots/reports remain ignored and private. Review [fresh release validation](RELEASE_VALIDATION.md) for what actually ran.
