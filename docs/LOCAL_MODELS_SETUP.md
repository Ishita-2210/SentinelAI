> Historical validation and setup notes. For this release pass, see [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md), [AI_MODELS.md](AI_MODELS.md) and the authoritative [hardware guide](HARDWARE_SETUP.md).

# Direct local VLM and LLM integration

Current presentation: `& D:\SentinelAI\scripts\run_presentation.ps1 -Source 0`, http://127.0.0.1:8010, both models enabled. Direct backend examples below use the separate default configuration/port. See [fresh validation](FINAL_VALIDATION.md).

Florence retains the trained adapter's question format. Base-model operation now uses parsed `<DETAILED_CAPTION>` observations and keeps the presence answer unknown. Results retain task and evidence SHA-256; corrupt image/request failures can retry in the same loaded worker. Timeouts and process exits still require a restart. SmolLM2 receives bounded records with missing-evidence and unverified-observation context; whole-record reduction preserves the question rather than silently truncating it. The application renders factual answers from SQLite.

## Audit and model choice
VLM was intentionally disabled by config.yaml and the previous --no-vlm command because the adapter was weak and Transformers 5.17 could not load the cached Florence remote implementation. Previous evaluation proved it could run under Transformers 4.49.0. An adapter exists at backend/vlm/models/sentinel-vqa-v1/best and loaded successfully in the integrated worker.

The old LLM module was an optional Ollama HTTP wrapper, not a working direct local Hugging Face implementation. That path has been replaced. Its previous source is archived under data/backups/before_local_ai. No Ollama dependency or inference server is used.

Inspected laptop: approximately 16 GB RAM, about 3.5 GB free at inspection, no CUDA. Selected model: HuggingFaceTB/SmolLM2-135M-Instruct. Its safetensors file is 269,060,552 bytes. Reserve roughly 1 GB disk for weights/tokenizer/cache copies on Windows, and additional memory for CPU float32 inference plus Florence and YOLO. Actual model processes are bounded to two CPU threads each by default. No quantization is required.

Model documentation: [SmolLM2 model card](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct). This is a small model with limited capability; no general-purpose assistant quality is claimed.

## Preserve the existing environment
```powershell
Set-Location D:\SentinelAI
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m pip install -r requirements-core.txt
```
The existing torch, Transformers 5.17, timm and einops installations remain intact. The VLM worker uses the already verified compatibility overlay with the same .venv Python executable:
```powershell
& .\.venv\Scripts\python.exe -m pip install --target data/evaluation/vlm_runtime --no-deps -r requirements-vlm-compat.txt
```
Run that installation only if the overlay is missing. It is not a new virtual environment and does not downgrade the main environment. The overlay pins Transformers 4.49.0, tokenizers 0.21.4, huggingface-hub 0.36.2 and PEFT 0.14.0. Existing optional Florence dependencies torch/timm/einops/accelerate must remain available.

## One-time LLM cache
The selected LLM has already been downloaded and actual inference succeeded on this machine. Check cached files without downloading:
```powershell
& .\.venv\Scripts\python.exe scripts/download_llm.py
```
On a fresh cache, explicitly permit the bounded one-time download:
```powershell
& .\.venv\Scripts\python.exe scripts/download_llm.py --download
```
Runtime workers use local_files_only and offline mode. Enabling a model never silently downloads weights or sends images/event data to an external inference service. The setup helper downloads public weights only.

## Launch combinations
Both enabled:
```powershell
& .\.venv\Scripts\python.exe -m backend.main --config config.yaml --source 0 --vlm --llm
```
VLM only:
```powershell
& .\.venv\Scripts\python.exe -m backend.main --config config.yaml --source 0 --vlm --no-llm
```
LLM only:
```powershell
& .\.venv\Scripts\python.exe -m backend.main --config config.yaml --source 0 --no-vlm --llm
```
Core perception only:
```powershell
& .\.venv\Scripts\python.exe -m backend.main --config config.yaml --source 0 --no-vlm --no-llm
```
The explicit CLI flags override YAML independently. Without flags, YAML controls enabling. Both remain opt-in by default. Open http://localhost:8000 while main is running.

A different cached LLM can be selected through llm.model_id or:
```powershell
$env:SENTINEL_LLM_MODEL = 'HuggingFaceTB/SmolLM2-135M-Instruct'
```
Changing this does not download weights. A missing cache produces an error state. Model inference failure or timeout is visible and does not stop perception; restart the application after correcting the cause.

## Test real model status and QA
In another PowerShell window:
```powershell
Invoke-RestMethod http://localhost:8000/api/models
Invoke-RestMethod http://localhost:8000/api/health
$questionBody = @{ question = 'When was the latest loitering event?'; limit = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/llm/query -ContentType 'application/json' -Body $questionBody
```
The dashboard's Ask event history panel exposes the same operation and source links. It shows generating, disabled/loading/error states, and timeouts without blocking live updates.

Supported examples: latest events, latest loitering, unattended-object records, last five minutes, events with VLM results, evidence for event #123, and around an ISO timestamp with an explicit timezone such as 2026-10-20T10:00:00+05:30. Around-time queries use a two-minute window on each side. No matching records yields an explicit statement, not an invented incident.

## Test Florence on an existing keyframe
After main has produced an event with evidence:
```powershell
$latestEvents = Invoke-RestMethod 'http://localhost:8000/api/events?limit=10'
$eventId = $latestEvents.events[0].id
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/events/$eventId/verify"
Invoke-RestMethod "http://localhost:8000/api/events/$eventId"
```
Poll that event until vlm_status becomes inconclusive or error. The dashboard also offers Check saved keyframe. Prompt, model, raw output, adapter flag, error and status-update time are persisted alongside the original event ID/track/timestamp/evidence. Automatic checks select LOITERING and UNATTENDED_OBJECT; unattended candidates have priority. The bounded queue deduplicates pending IDs. Results are deliberately inconclusive because the model is uncalibrated; a yes answer is a presence hypothesis and never proof of dwell or other temporal behavior.

## Grounding contract
SQLite retrieval applies event, ID and time filters first. The small LLM generates a constrained selection from retrieved IDs; generated IDs are validated again. All retrieved sources remain available. Factual answer text is rendered from the actual stored fields, not unrestricted model prose. This is deliberately extractive QA and source ordering, not open-ended generative summarization. API responses distinguish answer_kind=recorded_facts, llm_used, model_role, generation_status and source_event_ids. Unsupported model output is rejected and reported, while retrieved facts remain available. The LLM has no database-write or hardware-command tools.

## Separate real-weight tests
```powershell
& .\.venv\Scripts\python.exe scripts/smoke_local_models.py
& .\.venv\Scripts\python.exe scripts/verify_local_ai.py
# Independent synthetic-record contracts with a real authorized local keyframe:
& .\.venv\Scripts\python.exe scripts/evaluate_ai_grounding.py --base --image 'C:\path\to\keyframe.jpg'
```
These explicitly load real weights; ordinary pytest tests use mock IPC/model results. The full check uses port 8004 and a repeated-photo integration video, not the ESP32 camera. Actual results and screenshot: data/integration/end_to_end.json and dashboard_local_ai.png. Local worker diagnostics are in data/logs. The initial unconstrained output was rejected; the final constrained API and dashboard generations passed.
