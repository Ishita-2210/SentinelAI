"""Held-out VQA evaluation. No split edits, no training, one load per model."""
import argparse
import collections
import hashlib
import json
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LABELS = ("yes", "no", "unknown")

def metrics(rows):
    valid = [x for x in rows if not x.get("error")]
    cm = {g: {p: 0 for p in LABELS} for g in LABELS}
    for x in valid:
        cm[x["gold"]][x["prediction"]] += 1
    per_class = {}
    for label in LABELS:
        tp = cm[label][label]
        support = sum(cm[label].values())
        predicted = sum(cm[g][label] for g in LABELS)
        precision = tp / predicted if predicted else 0
        recall = tp / support if support else 0
        per_class[label] = dict(support=support, precision=precision, recall=recall,
                               f1=2*precision*recall/(precision+recall) if precision+recall else 0)
    unk = sum(cm["unknown"].values())
    return dict(n=len(rows), evaluated=len(valid), errors=len(rows)-len(valid),
                accuracy=sum(cm[g][g] for g in LABELS)/len(valid) if valid else None,
                confusion_matrix=cm, per_class=per_class,
                unknown_hallucination_rate=(unk-cm["unknown"]["unknown"])/unk if unk else None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dataset/test.jsonl")
    ap.add_argument("--output", default="data/evaluation/vlm")
    ap.add_argument("--base-model", default="microsoft/Florence-2-base-ft")
    ap.add_argument("--adapter", default="backend/vlm/models/sentinel-vqa-v1/best")
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    from backend.vlm_runtime.verifier import VisualVerifier
    split = ROOT / args.split
    records = [json.loads(line) for line in split.read_text().splitlines() if line.strip()]
    assert all(x["answer"] in LABELS for x in records)
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    report = dict(split=str(split), sha256=hashlib.sha256(split.read_bytes()).hexdigest(),
                  labels=dict(collections.Counter(x["answer"] for x in records)), models={})
    for name, adapter in (("base", None), ("adapter", str(ROOT/args.adapter))):
        rows = []
        try:
            verifier = VisualVerifier(base_model_id=args.base_model, adapter_dir=adapter, device="cpu")
            if adapter and not verifier.adapter_loaded:
                raise RuntimeError("Requested adapter did not load; refusing to score base model as adapter")
            with (out/(name+"_predictions.jsonl")).open("w", encoding="utf-8") as raw:
                for i, record in enumerate(records):
                    result = verifier.verify(split.parent/record["image_path"], record["question"])
                    row = dict(index=i, image_path=record["image_path"], question=record["question"],
                               gold=record["answer"], prediction=result.answer, raw_text=result.raw_text,
                               confidence=result.confidence, error=result.error)
                    rows.append(row)
                    raw.write(json.dumps(row)+"\n"); raw.flush()
                    print(name, i+1, len(records), result.answer, result.error, flush=True)
            report["models"][name] = metrics(rows)
            del verifier
            import gc
            gc.collect()
        except Exception as exc:
            report["models"][name] = dict(n=len(records), evaluated=len(rows), status="blocked", error=str(exc))
        (out/"metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
if __name__ == "__main__":
    main()
