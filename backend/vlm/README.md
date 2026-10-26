# SentinelAI VLM — legacy standalone experiments

This directory preserves the original standalone Florence-2 training and inference tools. The current application sends event evidence from [`backend/main.py`](../main.py) through [`AIManager`](../ai_runtime/manager.py) and [`ModelProcess`](../ai_runtime/process.py) to [`worker.py`](../ai_runtime/worker.py), which loads [`backend.vlm_runtime.verifier.VisualVerifier`](../vlm_runtime/verifier.py). It does not invoke `verify_standalone.py`.

Use the current [model setup](../../docs/AI_MODELS.md) and [accuracy evaluation](../../docs/ACCURACY_EVALUATION.md) for application configuration and interpretation. The commands below preserve the standalone experiment workflow; run them from this directory or an exported bundle. They are not application launch instructions, and a synthetic smoke test does not establish model quality.

The four original standalone files use no sibling-file imports and can be
kept together in Colab or on disk:

- `train_lora_standalone.py` — builds/validates the dataset, LoRA
  fine-tunes Florence-2, evaluates, saves the adapter. Runs with
  **zero arguments and zero prior setup**: if you don't pass `--raw`,
  it auto-generates a small synthetic dataset and trains on that, so
  you can confirm the whole pipeline works on your GPU before
  spending any time annotating. The resulting adapter from synthetic
  data is meaningless (colored shapes) — it only proves the code runs.
- `verify_standalone.py` — loads a (optionally LoRA-adapted) Florence-2
  model and answers yes/no/unknown for an (image, question) pair in
  the legacy standalone workflow.
- `requirements.txt` — `torch`, `transformers`, `peft`, etc.
- `README.md` — this file.

## 1. Zero-setup smoke test (prove it runs on your GPU)

```bash
pip install -r requirements.txt
python train_lora_standalone.py --epochs 2
```

No data needed. Watch for:
- `LoRA target modules: [...]` — should be non-empty
- per-epoch `train_loss`, `val_accuracy`, `val_unknown_hallucination_rate`
- `Done. Best val_accuracy=...` at the end, with files under `adapters/sentinel-vqa-v1/best/`

If that completes without errors, the environment and code are fine —
any future failure is a data problem, not a code/folder problem.

## 2. Validate a real annotation file without needing torch at all

```bash
python train_lora_standalone.py --raw raw_annotations.jsonl --image_root . --dry_run
```

`raw_annotations.jsonl`: one JSON object per line —
```json
{"image_id": "s001_q1", "scene_id": "scene_001", "image_path": "images/scene_001.jpg", "question": "Is the person holding the black backpack?", "answer": "yes", "relation": "holding"}
```
`answer` must be `yes` / `no` / `unknown`. `scene_id` groups
multiple questions about the same physical scene — the script splits
train/val/test by `scene_id` so the same background never appears in
both train and test. `image_path` is relative to `--image_root`.

This prints the same train/val/test class-balance report and warnings
(too few total examples, too little UNKNOWN) as a real run would, but
needs only Python's standard library — no GPU, no pip installs.

## 3. Real training run

```bash
python train_lora_standalone.py \
    --raw raw_annotations.jsonl --image_root . \
    --output_dir adapters/sentinel-vqa-v1 --epochs 8 --batch_size 4
```

Only proceed to this once step 2's report looks healthy (300+ total
records, ~20%+ UNKNOWN in every split).

## 4. Legacy standalone inference

```bash
python verify_standalone.py --image some_frame.jpg \
    --question "Is the person holding the bag?" \
    --adapter_dir adapters/sentinel-vqa-v1/best
```

Or from Python:
```python
from verify_standalone import VisualVerifier
verifier = VisualVerifier(adapter_dir="adapters/sentinel-vqa-v1/best")
result = verifier.verify(cropped_frame, "Is the person holding the bag?")
# {"answer": "yes", "raw_text": "yes"}
```

## Why this package looks different from the earlier one

The earlier `backend/vlm/` package split things into
`training/evaluation/dataset/inference/` folders with imports between
them — that's the normal way to organize a real project, but every
failure so far traced back to files ending up in the wrong folder
relative to each other after unzip/upload. This package trades that
organization for reliability: both scripts are fully self-contained,
so there's no folder structure to get wrong. Once your real training
is working end-to-end, you're welcome to go back to the modular
version for long-term maintenance — but this is the one to get
running first.
