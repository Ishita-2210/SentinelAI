"""LoRA fine-tuning of Florence-2 as SentinelAI's visual verifier.

Usage:
    python -m training.validate_dataset dataset
    python -m training.train_lora --dataset dataset --epochs 5
    python -m training.train_lora --dataset dataset --eval-only \
        --adapter training/outputs/lora-florence2

Then run the pipeline / API with:
    SENTINEL_VLM_ADAPTER=training/outputs/lora-florence2

The target is the output contract used at inference (see backend/vlm/vlm.py):
    YES: ... | NO: ... | UNKNOWN: ...

The prompt is built with backend.vlm.vlm.build_prompt, so training and
inference always use the same text. A GPU is strongly recommended.
"""

import argparse
import json
import random
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoProcessor

from backend.vlm.vlm import build_prompt, parse_verdict

LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "out_proj", "fc1", "fc2"]


class VerificationDataset(Dataset):

    def __init__(self, jsonl_path: Path, images_dir: Path):
        self.images_dir = images_dir
        self.records = [
            json.loads(line)
            for line in jsonl_path.read_text().splitlines()
            if line.strip()
        ]

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        record = self.records[index]

        image = Image.open(self.images_dir / record["image"]).convert("RGB")

        prompt = build_prompt(
            record["question"],
            record.get("detected_objects"),
        )

        return image, prompt, record["answer"]


def make_collate(processor, max_label_len: int):

    def collate(batch):
        images, prompts, answers = zip(*batch)

        inputs = processor(
            text=list(prompts),
            images=list(images),
            return_tensors="pt",
            padding=True,
        )

        labels = processor.tokenizer(
            list(answers),
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_label_len,
        ).input_ids

        labels[labels == processor.tokenizer.pad_token_id] = -100

        return inputs, labels

    return collate


def run_eval(model, processor, dataset, device, max_new_tokens=64):
    """Verdict accuracy and UNKNOWN rate on a split."""

    model.eval()

    correct = 0
    unknown_predicted = 0
    unknown_expected = 0
    unknown_correct = 0

    for image, prompt, answer in dataset:

        inputs = processor(text=prompt, images=image, return_tensors="pt").to(device)

        with torch.no_grad():
            generated = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"].to(model.dtype),
                max_new_tokens=max_new_tokens,
                num_beams=3,
                do_sample=False,
            )

        text = processor.batch_decode(generated, skip_special_tokens=True)[0]

        predicted, _ = parse_verdict(text)
        expected, _ = parse_verdict(answer)

        correct += predicted == expected
        unknown_predicted += predicted == "UNKNOWN"

        if expected == "UNKNOWN":
            unknown_expected += 1
            unknown_correct += predicted == "UNKNOWN"

    total = max(len(dataset), 1)

    return {
        "verdict_accuracy": correct / total,
        "unknown_rate_predicted": unknown_predicted / total,
        "unknown_recall": (
            unknown_correct / unknown_expected if unknown_expected else None
        ),
        "examples": len(dataset),
    }


def load_model(model_id, device, adapter=None):

    dtype = torch.float16 if device == "cuda" else torch.float32

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=dtype,
        trust_remote_code=True,
    )

    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)

    return model.to(device)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset")
    parser.add_argument("--model", default="microsoft/Florence-2-base-ft")
    parser.add_argument("--output", default="training/outputs/lora-florence2")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-label-len", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--adapter", default=None, help="adapter to evaluate")
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    root = Path(args.dataset)
    images = root / "images"

    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)

    val_set = VerificationDataset(root / "val.jsonl", images)
    test_path = root / "test.jsonl"

    # ---------------------------------
    # Evaluation only
    # ---------------------------------

    if args.eval_only:
        model = load_model(args.model, device, args.adapter)
        split = VerificationDataset(test_path, images) if test_path.exists() else val_set
        print(json.dumps(run_eval(model, processor, split, device), indent=2))
        return

    # ---------------------------------
    # Training
    # ---------------------------------

    from peft import LoraConfig, get_peft_model

    model = load_model(args.model, device)

    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=args.rank * 2,
            lora_dropout=0.05,
            target_modules=LORA_TARGETS,
            bias="none",
            task_type="CAUSAL_LM",
        ),
    )
    model.print_trainable_parameters()

    train_set = VerificationDataset(root / "train.jsonl", images)

    loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=make_collate(processor, args.max_label_len),
    )

    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=args.lr,
    )

    best_accuracy = -1.0
    output = Path(args.output)

    for epoch in range(1, args.epochs + 1):

        model.train()
        running = 0.0

        for step, (inputs, labels) in enumerate(loader, start=1):

            outputs = model(
                input_ids=inputs["input_ids"].to(device),
                pixel_values=inputs["pixel_values"].to(device, model.dtype),
                labels=labels.to(device),
            )

            outputs.loss.backward()
            optimizer.step()
            optimizer.zero_grad()

            running += outputs.loss.item()

        metrics = run_eval(model, processor, val_set, device)

        print(
            f"epoch {epoch}/{args.epochs} | "
            f"train loss {running / max(step, 1):.4f} | "
            f"val accuracy {metrics['verdict_accuracy']:.3f} | "
            f"val UNKNOWN recall {metrics['unknown_recall']}"
        )

        # Keep the best epoch by validation accuracy, not the last one.
        if metrics["verdict_accuracy"] > best_accuracy:
            best_accuracy = metrics["verdict_accuracy"]
            model.save_pretrained(output)
            print(f"  saved adapter to {output}")

    print(f"\nBest validation accuracy: {best_accuracy:.3f}")
    print("Evaluate on the held-out test split with:")
    print(f"  python -m training.train_lora --dataset {args.dataset} "
          f"--eval-only --adapter {output}")


if __name__ == "__main__":
    main()
