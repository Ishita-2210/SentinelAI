"""Validate the Florence-2 verification dataset before training.

Usage:
    python -m training.validate_dataset [dataset_dir]

Each line of train.jsonl / val.jsonl / test.jsonl must look like:

    {
      "image": "scene_001.jpg",
      "scene": "session_A",                      # recommended, see below
      "detected_objects": ["person", "bottle"],
      "question": "Is the person visibly holding the bottle?",
      "answer": "YES: The person is visibly holding the bottle."
    }

Checks:
  * required fields, image file exists (dataset_dir/images/<image>)
  * answer starts with YES: / NO: / UNKNOWN:
  * label balance per split (a model trained on 95% YES learns to say YES)
  * no scene appears in more than one split. Near-duplicate video frames
    from the same recording leak between train and test otherwise and
    inflate accuracy. Set "scene" to the recording session id; if it is
    missing the image file name without its trailing frame number is used.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = ("image", "detected_objects", "question", "answer")
SPLITS = ("train", "val", "test")
ANSWER_PATTERN = re.compile(r"^(YES|NO|UNKNOWN):\s*\S")


def scene_of(record: dict) -> str:
    if record.get("scene"):
        return str(record["scene"])

    stem = Path(record["image"]).stem
    return re.sub(r"[_-]?\d+$", "", stem) or stem


def load_split(path: Path):
    records, errors = [], []

    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue

        try:
            records.append((number, json.loads(line)))
        except json.JSONDecodeError as error:
            errors.append(f"{path.name}:{number}: invalid JSON ({error})")

    return records, errors


def main():

    root = Path(sys.argv[1] if len(sys.argv) > 1 else "dataset")
    images_dir = root / "images"

    errors: list[str] = []
    warnings: list[str] = []
    scenes_by_split: dict[str, set] = defaultdict(set)

    print(f"Validating {root}/\n")

    for split in SPLITS:

        path = root / f"{split}.jsonl"

        if not path.exists():
            if split == "test":
                warnings.append("test.jsonl is missing (needed for a final evaluation)")
            else:
                errors.append(f"{split}.jsonl is missing")
            continue

        records, parse_errors = load_split(path)
        errors.extend(parse_errors)

        labels = Counter()

        for number, record in records:
            where = f"{path.name}:{number}"

            missing = [key for key in REQUIRED if key not in record]
            if missing:
                errors.append(f"{where}: missing {missing}")
                continue

            if not (images_dir / record["image"]).is_file():
                errors.append(f"{where}: image not found: {record['image']}")

            match = ANSWER_PATTERN.match(record["answer"])
            if not match:
                errors.append(
                    f"{where}: answer must start with YES:/NO:/UNKNOWN: and "
                    f"give a reason, got {record['answer'][:40]!r}"
                )
            else:
                labels[match.group(1)] += 1

            scenes_by_split[split].add(scene_of(record))

        total = sum(labels.values())

        print(f"{split:5s} {len(records):5d} examples | scenes: "
              f"{len(scenes_by_split[split])}")

        for label in ("YES", "NO", "UNKNOWN"):
            share = labels[label] / total * 100 if total else 0
            print(f"        {label:8s} {labels[label]:5d} ({share:4.1f}%)")

            if split == "train" and total >= 20 and share < 10:
                warnings.append(
                    f"train has only {share:.0f}% {label} examples; add more "
                    f"so the model does not collapse to the majority answer"
                )

    # Leakage between splits
    for first in SPLITS:
        for second in SPLITS:
            if first >= second:
                continue

            shared = scenes_by_split[first] & scenes_by_split[second]

            if shared:
                errors.append(
                    f"scene leakage between {first} and {second}: "
                    f"{sorted(shared)[:5]}"
                )

    print()

    for warning in warnings:
        print(f"WARNING: {warning}")

    for error in errors[:50]:
        print(f"ERROR: {error}")

    if len(errors) > 50:
        print(f"... and {len(errors) - 50} more errors")

    if errors:
        print(f"\nFAILED with {len(errors)} error(s).")
        sys.exit(1)

    print("OK: dataset is valid.")


if __name__ == "__main__":
    main()
