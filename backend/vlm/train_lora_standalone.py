"""
SentinelAI Florence-2 LoRA fine-tuning — fully standalone, single file.

Zero sibling-file imports: metrics, dataset splitting/validation, the
PyTorch Dataset + collate function, and the training loop are ALL
defined in this one file. There is nothing else to place in the wrong
folder — drop this file anywhere and run it.

Zero-setup smoke test: if you don't pass --raw (or the path you pass
doesn't exist), this script auto-generates a small synthetic dataset
(colored shapes, made-up questions) and trains on that, so

    python train_lora_standalone.py

with NO arguments at all will run to completion on a T4/L4 and prove
the whole pipeline works (Florence-2 loads, LoRA attaches, training
loop runs, adapter saves, eval runs).

>>> THE RESULTING ADAPTER FROM SYNTHETIC DATA IS MEANINGLESS. <<<
It's colored blobs, not your real scenes — it proves the code works,
not that the model learned anything useful. Once you have real
annotations, point --raw / --image_root at them for an actual run.

Usage:
    # zero-setup smoke test (auto-generates fake data, ~2 min on a T4)
    python train_lora_standalone.py --epochs 2

    # real run with an existing train/val/test split + images/
    python train_lora_standalone.py \
        --data_dir ../dataset --image_root ../dataset \
        --output_dir adapters/sentinel-vqa-v1 --epochs 8

    # legacy raw-data mode is still supported
    python train_lora_standalone.py \
        --raw raw_annotations.jsonl --image_root . \
        --output_dir adapters/sentinel-vqa-v1 --epochs 8

    # validate just the data file (scene split, class balance) —
    # no GPU, no torch/transformers/peft needed at all
    python train_lora_standalone.py --raw raw_annotations.jsonl --image_root . --dry_run

Only Python's standard library is needed for --dry_run and --help.
Pillow is needed to generate/read images. torch + transformers + peft
are needed for an actual training run (see requirements.txt).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

# =============================================================================
# metrics (no deps beyond stdlib)
# =============================================================================
LABELS = ("yes", "no", "unknown")


def normalize_answer(raw: str) -> str:
    """Map a model's free-text generation to one of yes/no/unknown."""
    text = raw.strip().lower()
    if text.startswith("unknown") or "cannot" in text or "not sure" in text or "insufficient" in text:
        return "unknown"
    if text.startswith("yes"):
        return "yes"
    if text.startswith("no"):
        return "no"
    if "unknown" in text:
        return "unknown"
    if "yes" in text and "no" not in text:
        return "yes"
    if "no" in text and "yes" not in text:
        return "no"
    return "unknown"


def compute_metrics(gold: list[str], pred: list[str]) -> dict:
    assert len(gold) == len(pred), f"{len(gold)} gold vs {len(pred)} pred"

    confusion = {g: {p: 0 for p in LABELS} for g in LABELS}
    correct = 0
    for g, p in zip(gold, pred):
        confusion[g][p] += 1
        if g == p:
            correct += 1
    accuracy = correct / len(gold) if gold else 0.0

    per_class = {}
    for label in LABELS:
        tp = confusion[label][label]
        fn = sum(confusion[label][p] for p in LABELS if p != label)
        fp = sum(confusion[g][label] for g in LABELS if g != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}

    true_unknown = confusion["unknown"]
    unknown_support = sum(true_unknown.values())
    unknown_hallucinations = true_unknown["yes"] + true_unknown["no"]
    unknown_hallucination_rate = unknown_hallucinations / unknown_support if unknown_support else 0.0

    return {
        "accuracy": accuracy,
        "per_class": per_class,
        "confusion_matrix": confusion,
        "unknown_hallucination_rate": unknown_hallucination_rate,
        "n": len(gold),
    }


# =============================================================================
# dataset validation + scene-aware splitting (no deps beyond stdlib)
# =============================================================================
REQUIRED_FIELDS = {"image_id", "scene_id", "image_path", "question", "answer"}
VALID_ANSWERS = {"yes", "no", "unknown"}


def validate_record(record: dict) -> list[str]:
    errors = []
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")
    ans = str(record.get("answer", "")).strip().lower()
    if ans not in VALID_ANSWERS:
        errors.append(f"invalid answer '{record.get('answer')}', must be one of {VALID_ANSWERS}")
    return errors


def validate_dataset(records) -> list[str]:
    all_errors = []
    for i, r in enumerate(records):
        errs = validate_record(r)
        if errs:
            all_errors.append(f"record {i} ({r.get('image_id', '?')}): {'; '.join(errs)}")
    return all_errors


def split_by_scene(records, val_frac=0.15, test_frac=0.20, seed=42):
    by_scene = defaultdict(list)
    for r in records:
        by_scene[r["scene_id"]].append(r)

    scene_ids = list(by_scene.keys())
    rng = random.Random(seed)
    rng.shuffle(scene_ids)

    total = len(records)
    target_test = total * test_frac
    target_val = total * val_frac

    test, val, train = [], [], []
    running = 0
    for sid in scene_ids:
        group = by_scene[sid]
        if running < target_test:
            test.extend(group)
        elif running < target_test + target_val:
            val.extend(group)
        else:
            train.extend(group)
        running += len(group)
    return train, val, test


def class_counts(records) -> dict:
    counts = {"yes": 0, "no": 0, "unknown": 0}
    for r in records:
        counts[str(r["answer"]).strip().lower()] += 1
    return counts


def scenes_are_disjoint(*splits) -> bool:
    seen = set()
    for split in splits:
        ids = {r["scene_id"] for r in split}
        if seen & ids:
            return False
        seen |= ids
    return True


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no} is not valid JSON: {e}") from e
    return records


def write_jsonl(records, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# =============================================================================
# synthetic smoke-test data (needs Pillow, nothing else)
# =============================================================================
def generate_synthetic_dataset(out_dir: Path, n_scenes: int = 30, questions_per_scene: int = 3, seed: int = 0):
    """Writes out_dir/images/*.jpg + out_dir/raw_annotations.jsonl of
    colored-shape images with made-up yes/no/unknown questions. Used
    only when the caller doesn't supply real data."""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    colors = ["red", "blue", "green", "yellow", "purple", "orange", "cyan", "magenta"]
    relations = ["holding", "touching", "near", "separated", "visibility", "posture"]
    answers = ["yes", "no", "unknown"]

    records = []
    for s in range(n_scenes):
        bg = rng.choice(colors)
        fg = rng.choice([c for c in colors if c != bg])
        img = Image.new("RGB", (224, 224), color=bg)
        draw = ImageDraw.Draw(img)
        x0, y0 = rng.randint(10, 80), rng.randint(10, 80)
        x1, y1 = x0 + rng.randint(60, 120), y0 + rng.randint(60, 120)
        draw.ellipse((x0, y0, min(x1, 214), min(y1, 214)), fill=fg)
        img_path = f"images/scene_{s}.jpg"
        img.save(out_dir / img_path)

        for q in range(questions_per_scene):
            records.append({
                "image_id": f"s{s}_q{q}",
                "scene_id": f"scene_{s}",
                "image_path": img_path,
                "question": f"Is shape {q} visible in this synthetic scene?",
                "answer": answers[(s + q) % 3],
                "relation": relations[(s + q) % len(relations)],
            })

    raw_path = out_dir / "raw_annotations.jsonl"
    write_jsonl(records, raw_path)
    return raw_path, out_dir


# =============================================================================
# PyTorch Dataset + collate (duck-typed map-style dataset; no need to
# inherit torch.utils.data.Dataset for DataLoader to accept it)
# =============================================================================
class Florence2VQADataset:
    def __init__(self, records: list[dict], image_root: Path, prompt_template: str):
        self.records = records
        self.image_root = Path(image_root)
        self.prompt_template = prompt_template

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int):
        from PIL import Image
        r = self.records[idx]
        image = Image.open(self.image_root / r["image_path"]).convert("RGB")
        prompt = self.prompt_template.format(question=r["question"].strip())
        return {"image": image, "prompt": prompt, "answer": r["answer"], "image_id": r["image_id"]}


def make_collate_fn(processor):
    def collate_fn(batch):
        images = [b["image"] for b in batch]
        prompts = [b["prompt"] for b in batch]
        answers = [b["answer"] for b in batch]

        inputs = processor(text=prompts, images=images, return_tensors="pt", padding=True)

        label_ids = processor.tokenizer(text=answers, return_tensors="pt", padding=True).input_ids
        pad_id = processor.tokenizer.pad_token_id
        label_ids[label_ids == pad_id] = -100

        inputs["labels"] = label_ids
        inputs["image_ids"] = [b["image_id"] for b in batch]
        return inputs

    return collate_fn


# =============================================================================
# model loading + LoRA + train/eval loops (torch/transformers/peft are
# imported lazily, INSIDE these functions, so --help/--dry_run work
# without those packages installed at all)
# =============================================================================
def load_base_model(model_id: str, device: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    dtype = torch.float16 if device == "cuda" else torch.float32
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, trust_remote_code=True, torch_dtype=dtype, attn_implementation="sdpa",
        )
        print(f"Loaded {model_id} (attn_implementation='sdpa')")
    except Exception as e:
        print(f"attn_implementation='sdpa' failed ({e}); falling back to default")
        model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True, torch_dtype=dtype)
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    return model.to(device), processor


def discover_target_modules(model, keywords) -> list[str]:
    import torch
    found = set()
    for name, module in model.named_modules():
        if not isinstance(module, torch.nn.Linear):
            continue
        leaf = name.split(".")[-1]
        if any(kw in leaf for kw in keywords):
            found.add(leaf)
    if not found:
        raise RuntimeError(
            "No matching Linear layers found for LoRA target_modules. Print "
            "model.named_modules() and update --target_module_keywords."
        )
    return sorted(found)


def freeze_vision_tower(model) -> None:
    frozen = 0
    for name, param in model.named_parameters():
        if "vision_tower" in name or "image_encoder" in name or "vision_model" in name:
            param.requires_grad = False
            frozen += 1
    print(f"Froze {frozen} vision-tower parameters")


def move_batch_to_device(batch, device, model):
    """Move a Florence-2 batch safely to device and force image tensors to
    the actual base vision-layer dtype.

    Important: PEFT/LoRA parameters can be FP32 even when the frozen base
    Florence-2 vision tower is FP16. Do NOT infer the image dtype from the
    first parameter whose name contains ``vision_tower``; that can accidentally
    pick a LoRA parameter and recreate the float-vs-half Conv2d error.
    """
    import torch

    # Florence-2 is loaded as FP16 on CUDA by load_base_model(). Use the
    # actual base Conv/Linear layer dtype when possible, explicitly skipping
    # LoRA adapter parameters.
    vision_dtype = None

    for name, param in model.named_parameters():
        lname = name.lower()
        is_vision = (
            "vision_tower" in lname
            or "image_encoder" in lname
            or "vision_model" in lname
        )
        is_adapter = (
            "lora_" in lname
            or "modules_to_save" in lname
        )
        if is_vision and not is_adapter and param.is_floating_point():
            vision_dtype = param.dtype
            break

    # Fallback is deterministic because load_base_model() uses exactly this
    # dtype for CUDA/CPU.
    if vision_dtype is None:
        vision_dtype = torch.float16 if device == "cuda" else torch.float32

    moved = {}
    for key, value in batch.items():
        if not torch.is_tensor(value):
            moved[key] = value
        elif key == "pixel_values":
            moved[key] = value.to(
                device=device,
                dtype=vision_dtype,
                non_blocking=True,
            )
        else:
            moved[key] = value.to(
                device=device,
                non_blocking=True,
            )

    return moved


def verify_input_dtypes(model, dataloader, device):
    """Fail early with a useful message if image/model dtypes disagree."""
    import torch

    batch = next(iter(dataloader))
    batch = move_batch_to_device(batch, device, model)

    pixel_dtype = batch["pixel_values"].dtype

    vision_dtype = None
    for name, param in model.named_parameters():
        lname = name.lower()
        if (
            ("vision_tower" in lname or "image_encoder" in lname or "vision_model" in lname)
            and "lora_" not in lname
            and "modules_to_save" not in lname
            and param.is_floating_point()
        ):
            vision_dtype = param.dtype
            break

    if vision_dtype is None:
        vision_dtype = torch.float16 if device == "cuda" else torch.float32

    print(
        f"dtype check: pixel_values={pixel_dtype}, "
        f"base_vision={vision_dtype}, device={device}"
    )

    if pixel_dtype != vision_dtype:
        raise RuntimeError(
            f"dtype mismatch before forward pass: "
            f"pixel_values={pixel_dtype}, base vision={vision_dtype}"
        )


def run_eval(model, processor, dataset, device, batch_size=8, max_new_tokens=4):
    import torch
    from torch.utils.data import DataLoader

    model.eval()
    collate_fn = make_collate_fn(processor)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_fn)

    predictions = []
    with torch.no_grad():
        for batch in loader:
            batch.pop("image_ids")
            batch.pop("labels")
            batch = move_batch_to_device(batch, device, model)
            generated = model.generate(**batch, max_new_tokens=max_new_tokens, num_beams=1, do_sample=False)
            decoded = processor.batch_decode(generated, skip_special_tokens=True)
            predictions.extend(normalize_answer(d) for d in decoded)

    gold = [dataset.records[i]["answer"] for i in range(len(dataset))]
    return compute_metrics(gold, predictions)


def train(args, train_records, val_records):
    import torch
    from torch.utils.data import DataLoader
    from transformers import get_cosine_schedule_with_warmup
    from peft import LoraConfig, get_peft_model

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("WARNING: no GPU found. Use Runtime > Change runtime type > T4/L4 in Colab.")

    model, processor = load_base_model(args.base_model_id, device)
    if args.freeze_vision_tower:
        freeze_vision_tower(model)

    keywords = args.target_module_keywords.split(",")
    target_modules = discover_target_modules(model, keywords)
    print(f"LoRA target modules: {target_modules}")

    lora_config = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
        target_modules=target_modules, task_type="CAUSAL_LM", bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    train_ds = Florence2VQADataset(train_records, args.image_root, args.prompt_template)
    val_ds = Florence2VQADataset(val_records, args.image_root, args.prompt_template)
    print(f"train={len(train_ds)}  val={len(val_ds)}")

    collate_fn = make_collate_fn(processor)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, collate_fn=collate_fn)
    verify_input_dtypes(model, train_loader, device)

    steps_per_epoch = max(1, len(train_loader) // args.grad_accum_steps)
    total_steps = steps_per_epoch * args.epochs
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.learning_rate, weight_decay=args.weight_decay,
    )
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, num_warmup_steps=int(total_steps * args.warmup_ratio), num_training_steps=total_steps,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    best_val_acc = -1.0

    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        optimizer.zero_grad()

        for step, batch in enumerate(train_loader):
            batch.pop("image_ids")
            batch = move_batch_to_device(batch, device, model)
            outputs = model(**batch)
            loss = outputs.loss / args.grad_accum_steps
            loss.backward()
            running_loss += loss.item() * args.grad_accum_steps

            if (step + 1) % args.grad_accum_steps == 0:
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

        avg_loss = running_loss / len(train_loader)
        print(f"epoch {epoch + 1}/{args.epochs}  train_loss={avg_loss:.4f}")

        if len(val_ds) == 0:
            print("  (val split is empty — skipping eval this epoch, add more data/scenes)")
            continue

        val_metrics = run_eval(model, processor, val_ds, device, max_new_tokens=args.max_new_tokens)
        print(f"  val_accuracy={val_metrics['accuracy']:.4f}  "
              f"val_unknown_hallucination_rate={val_metrics['unknown_hallucination_rate']:.4f}  "
              f"val_confusion={val_metrics['confusion_matrix']}")

        if val_metrics["accuracy"] > best_val_acc:
            best_val_acc = val_metrics["accuracy"]
            model.save_pretrained(output_dir / "best")
            processor.save_pretrained(output_dir / "best")
            with open(output_dir / "best" / "val_metrics.json", "w") as f:
                json.dump(val_metrics, f, indent=2)
            print(f"  new best (val_accuracy={best_val_acc:.4f}), saved to {output_dir / 'best'}")

    model.save_pretrained(output_dir / "last")
    processor.save_pretrained(output_dir / "last")
    print(f"\nDone. Best val_accuracy={best_val_acc:.4f}. Adapters in {output_dir}")


# =============================================================================
# CLI
# =============================================================================
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=None,
                     help="path to raw_annotations.jsonl. Legacy mode: if omitted, use --data_dir first.")
    ap.add_argument("--data_dir", default=None,
                     help="folder containing existing train.jsonl, val.jsonl, test.jsonl and images/")
    ap.add_argument("--image_root", default=None, help="folder image_path in annotations is relative to")
    ap.add_argument("--output_dir", default="adapters/sentinel-vqa-v1")
    ap.add_argument("--base_model_id", default="microsoft/Florence-2-base-ft")
    ap.add_argument("--prompt_template", default="{question} Answer only with yes, no, or unknown.")
    ap.add_argument("--max_new_tokens", type=int, default=4)
    ap.add_argument("--val_frac", type=float, default=0.15)
    ap.add_argument("--test_frac", type=float, default=0.20)
    ap.add_argument("--lora_r", type=int, default=8)
    ap.add_argument("--lora_alpha", type=int, default=16)
    ap.add_argument("--lora_dropout", type=float, default=0.05)
    ap.add_argument("--target_module_keywords",
                     default="q_proj,k_proj,v_proj,out_proj,o_proj,fc1,fc2,qkv,proj")
    ap.add_argument("--freeze_vision_tower", action="store_true", default=True)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch_size", type=int, default=4)
    ap.add_argument("--grad_accum_steps", type=int, default=2)
    ap.add_argument("--learning_rate", type=float, default=1e-4)
    ap.add_argument("--weight_decay", type=float, default=0.01)
    ap.add_argument("--warmup_ratio", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry_run", action="store_true",
                     help="only load/validate/split the data and print a report; no torch, "
                          "transformers, peft, or GPU required")
    ap.add_argument("--synthetic_scenes", type=int, default=30,
                     help="how many fake scenes to generate when --raw is omitted/missing")
    return ap


def main():
    args = build_arg_parser().parse_args()

    # ---- load an existing split dataset, or use legacy raw/synthetic mode ----
    using_presplit = False
    using_synthetic = False

    if args.data_dir is not None:
        data_dir = Path(args.data_dir)
        train_path = data_dir / "train.jsonl"
        val_path = data_dir / "val.jsonl"
        test_path = data_dir / "test.jsonl"
        missing = [str(p) for p in (train_path, val_path, test_path) if not p.exists()]
        if missing:
            raise SystemExit("Missing required split file(s): " + ", ".join(missing))

        using_presplit = True
        if args.image_root is None:
            args.image_root = str(data_dir)
        train_records = load_jsonl(train_path)
        val_records = load_jsonl(val_path)
        test_records = load_jsonl(test_path)
        all_records = train_records + val_records + test_records
        print(f"Using EXISTING split dataset: {data_dir}")
        print(f"Loaded existing splits: train={len(train_records)}, val={len(val_records)}, test={len(test_records)}")

        errors = validate_dataset(all_records)
        if errors:
            print(f"\n{len(errors)} validation error(s):")
            for e in errors[:20]:
                print(f"  - {e}")
            raise SystemExit("Fix the dataset before training.")

        assert scenes_are_disjoint(train_records, val_records, test_records), "scene leakage between existing splits!"
    else:
        using_synthetic = args.raw is None or not Path(args.raw).exists()
        if using_synthetic:
            print("=" * 70)
            print("No --data_dir or valid --raw supplied — auto-generating a")
            print("SYNTHETIC smoke-test dataset. The resulting model is MEANINGLESS;")
            print("this only proves the pipeline runs.")
            print("=" * 70)
            synth_dir = Path("_synthetic_smoketest_data")
            raw_path, image_root = generate_synthetic_dataset(synth_dir, n_scenes=args.synthetic_scenes)
            args.raw = str(raw_path)
            args.image_root = str(image_root)
        else:
            if args.image_root is None:
                args.image_root = "."
            print(f"Using real raw data: {args.raw}  (image_root={args.image_root})")

        all_records = load_jsonl(Path(args.raw))
        print(f"Loaded {len(all_records)} raw records")

        errors = validate_dataset(all_records)
        if errors:
            print(f"\n{len(errors)} validation error(s):")
            for e in errors[:20]:
                print(f"  - {e}")
            raise SystemExit("Fix the raw annotations before training.")

        train_records, val_records, test_records = split_by_scene(
            all_records, val_frac=args.val_frac, test_frac=args.test_frac, seed=args.seed
        )
        assert scenes_are_disjoint(train_records, val_records, test_records), "scene leakage between splits!"

    def report(name, split):
        c = class_counts(split)
        print(f"  {name:5s}: total={len(split):4d}  yes={c['yes']:4d}  no={c['no']:4d}  unknown={c['unknown']:4d}")

    print("\nSplit report (by scene, not by record):")
    report("train", train_records)
    report("val", val_records)
    report("test", test_records)

    if not using_synthetic:
        total = len(all_records)
        if total < 300:
            print(f"\nWARNING: only {total} total records. Aim for 300+ before trusting the model.")
        for name, split in (("train", train_records), ("val", val_records), ("test", test_records)):
            c = class_counts(split)
            n = len(split) or 1
            if c["unknown"] / n < 0.20:
                print(f"WARNING: '{name}' split is only {c['unknown']/n:.0%} UNKNOWN (target >= 20%).")

    if args.dry_run:
        print("\n--dry_run set: stopping here. No model loaded, nothing trained.")
        return

    train(args, train_records, val_records)


if __name__ == "__main__":
    main()
