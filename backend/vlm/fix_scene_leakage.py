import json
import random
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(r"..\..\dataset").resolve()

SPLITS = {
    "train": DATA_DIR / "train.jsonl",
    "val": DATA_DIR / "val.jsonl",
    "test": DATA_DIR / "test.jsonl",
}

SEED = 42

# Desired approximate proportions.
# Your current dataset is 113 / 28 / 37 = 178 records.
TRAIN_RATIO = 0.64
VAL_RATIO = 0.16
TEST_RATIO = 0.20


def load_jsonl(path):
    records = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line:
                records.append(json.loads(line))

    return records


def save_jsonl(path, records):
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False
                ) + "\n"
            )


def get_group_key(record):
    """
    Group all questions belonging to the same image/scene.

    Prefer scene_id when present.
    Fall back to image_id/image_path.
    """

    scene_id = record.get("scene_id")

    if scene_id:
        return f"scene::{scene_id}"

    image_id = record.get("image_id")

    if image_id:
        return f"image::{image_id}"

    image_path = record.get("image_path")

    if image_path:
        return f"path::{image_path}"

    raise ValueError(
        "Record has no scene_id, image_id, or image_path:\n"
        + str(record)
    )


def count_records(groups):
    return sum(len(records) for records in groups.values())


def main():

    print("=" * 70)
    print("SentinelAI - Scene Leakage Fix")
    print("=" * 70)

    print()
    print("Dataset:", DATA_DIR)

    if not DATA_DIR.exists():
        raise FileNotFoundError(DATA_DIR)

    # ---------------------------------------------------------
    # LOAD ALL RECORDS
    # ---------------------------------------------------------

    all_records = []

    for split_name, path in SPLITS.items():

        if not path.exists():
            raise FileNotFoundError(path)

        records = load_jsonl(path)

        print(
            f"{split_name}: loaded {len(records)} records"
        )

        all_records.extend(records)

    print()
    print("Total records:", len(all_records))

    # ---------------------------------------------------------
    # GROUP BY SCENE / IMAGE
    # ---------------------------------------------------------

    groups = defaultdict(list)

    for record in all_records:
        key = get_group_key(record)
        groups[key].append(record)

    print(
        "Unique scene/image groups:",
        len(groups)
    )

    # ---------------------------------------------------------
    # SHOW GROUPS THAT ARE CURRENTLY LEAKING
    # ---------------------------------------------------------

    current_membership = defaultdict(set)

    for split_name, path in SPLITS.items():

        records = load_jsonl(path)

        for record in records:

            key = get_group_key(record)

            current_membership[key].add(split_name)

    leaking = {
        key: splits
        for key, splits in current_membership.items()
        if len(splits) > 1
    }

    print()

    if leaking:

        print(
            f"FOUND {len(leaking)} LEAKING SCENE/IMAGE GROUP(S)"
        )

        print()

        for key, splits in list(leaking.items())[:20]:

            print(
                f"  {key} -> {sorted(splits)}"
            )

        if len(leaking) > 20:
            print(
                f"  ... and {len(leaking) - 20} more"
            )

    else:

        print("No leakage found.")
        return

    # ---------------------------------------------------------
    # BACK UP EXISTING DATASET
    # ---------------------------------------------------------

    for split_name, path in SPLITS.items():

        backup = path.with_suffix(
            path.suffix + ".pre_scene_fix.bak"
        )

        if not backup.exists():
            path.replace(backup)

            # Restore source path for later writing
            print(
                f"Backed up {split_name}.jsonl"
            )

    # ---------------------------------------------------------
    # RELOAD FROM BACKUPS
    # ---------------------------------------------------------

    source_files = {
        split_name: path.with_suffix(
            path.suffix + ".pre_scene_fix.bak"
        )
        for split_name, path in SPLITS.items()
    }

    all_records = []

    for split_name, path in source_files.items():
        records = load_jsonl(path)
        all_records.extend(records)

    # ---------------------------------------------------------
    # REGROUP
    # ---------------------------------------------------------

    groups = defaultdict(list)

    for record in all_records:
        groups[get_group_key(record)].append(record)

    # ---------------------------------------------------------
    # SHUFFLE GROUPS, NOT INDIVIDUAL RECORDS
    # ---------------------------------------------------------

    rng = random.Random(SEED)

    group_items = list(groups.items())

    rng.shuffle(group_items)

    total_records = len(all_records)

    target_train = round(total_records * TRAIN_RATIO)
    target_val = round(total_records * VAL_RATIO)

    train_records = []
    val_records = []
    test_records = []

    # ---------------------------------------------------------
    # ASSIGN COMPLETE GROUPS
    # ---------------------------------------------------------

    for key, records in group_items:

        if len(train_records) < target_train:
            train_records.extend(records)

        elif len(val_records) < target_val:
            val_records.extend(records)

        else:
            test_records.extend(records)

    # ---------------------------------------------------------
    # WRITE NEW SPLITS
    # ---------------------------------------------------------

    new_splits = {
        "train": train_records,
        "val": val_records,
        "test": test_records,
    }

    for split_name, records in new_splits.items():

        save_jsonl(
            SPLITS[split_name],
            records
        )

    # ---------------------------------------------------------
    # VERIFY NO LEAKAGE
    # ---------------------------------------------------------

    split_groups = {}

    for split_name, records in new_splits.items():

        split_groups[split_name] = {
            get_group_key(record)
            for record in records
        }

    train_groups = split_groups["train"]
    val_groups = split_groups["val"]
    test_groups = split_groups["test"]

    overlap_train_val = train_groups & val_groups
    overlap_train_test = train_groups & test_groups
    overlap_val_test = val_groups & test_groups

    print()
    print("=" * 70)
    print("NEW SPLIT REPORT")
    print("=" * 70)

    for split_name, records in new_splits.items():

        answers = [
            str(r.get("answer", "")).lower()
            for r in records
        ]

        yes = answers.count("yes")
        no = answers.count("no")
        unknown = answers.count("unknown")

        print(
            f"{split_name:5s}: "
            f"total={len(records):3d} "
            f"yes={yes:3d} "
            f"no={no:3d} "
            f"unknown={unknown:3d} "
            f"groups={len(split_groups[split_name]):3d}"
        )

    print()
    print("Train/Val overlap :", len(overlap_train_val))
    print("Train/Test overlap:", len(overlap_train_test))
    print("Val/Test overlap  :", len(overlap_val_test))

    if (
        overlap_train_val
        or overlap_train_test
        or overlap_val_test
    ):
        raise RuntimeError(
            "Scene leakage STILL EXISTS."
        )

    print()
    print("=" * 70)
    print("SCENE LEAKAGE FIXED SUCCESSFULLY")
    print("=" * 70)

    print()
    print("Backups:")
    print("  train.jsonl.pre_scene_fix.bak")
    print("  val.jsonl.pre_scene_fix.bak")
    print("  test.jsonl.pre_scene_fix.bak")

    print()
    print("Your dataset is now scene-disjoint.")


if __name__ == "__main__":
    main()