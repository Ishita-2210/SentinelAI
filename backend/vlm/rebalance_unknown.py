import json
import shutil
import random
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(r"..\..\dataset").resolve()

FILES = {
    "train": DATA_DIR / "train.jsonl",
    "val": DATA_DIR / "val.jsonl",
    "test": DATA_DIR / "test.jsonl",
}

SEED = 42


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def scene_key(record):
    if record.get("scene_id"):
        return str(record["scene_id"])

    if record.get("image_id"):
        return f"image_{record['image_id']}"

    return f"path_{record['image_path']}"


def stats(records):
    answers = [str(r["answer"]).lower() for r in records]

    return {
        "total": len(records),
        "yes": answers.count("yes"),
        "no": answers.count("no"),
        "unknown": answers.count("unknown"),
    }


def main():

    print("=" * 70)
    print("SentinelAI UNKNOWN Rebalancer")
    print("=" * 70)

    data = {
        split: load(path)
        for split, path in FILES.items()
    }

    print("\nBEFORE:")

    for split, records in data.items():
        print(split, stats(records))

    # ---------------------------------------------------------
    # Backups
    # ---------------------------------------------------------

    for split, path in FILES.items():

        backup = path.with_suffix(
            path.suffix + ".before_unknown_rebalance.bak"
        )

        if not backup.exists():
            shutil.copy2(path, backup)

    # ---------------------------------------------------------
    # Group records by scene
    # ---------------------------------------------------------

    scene_groups = {}

    for split, records in data.items():

        groups = defaultdict(list)

        for record in records:
            groups[scene_key(record)].append(record)

        scene_groups[split] = groups

    # ---------------------------------------------------------
    # Find train scenes containing UNKNOWN
    # ---------------------------------------------------------

    train_unknown_groups = []

    for scene, records in scene_groups["train"].items():

        unknown_count = sum(
            str(r["answer"]).lower() == "unknown"
            for r in records
        )

        if unknown_count > 0:
            train_unknown_groups.append(
                (scene, records, unknown_count)
            )

    random.Random(SEED).shuffle(train_unknown_groups)

    # ---------------------------------------------------------
    # Move a few complete scenes.
    #
    # We do NOT split records belonging to the same scene.
    # ---------------------------------------------------------

    move_to_val = 2
    move_to_test = 2

    moved_scenes = set()

    # Pick scenes with fewer records first so split sizes
    # don't change too dramatically.
    train_unknown_groups.sort(
        key=lambda x: len(x[1])
    )

    val_candidates = train_unknown_groups[:move_to_val]

    remaining = [
        x for x in train_unknown_groups
        if x[0] not in {v[0] for v in val_candidates}
    ]

    test_candidates = remaining[:move_to_test]

    # ---------------------------------------------------------
    # Move selected scenes
    # ---------------------------------------------------------

    for scene, records, unknown_count in val_candidates:

        data["train"] = [
            r for r in data["train"]
            if scene_key(r) != scene
        ]

        data["val"].extend(records)

        moved_scenes.add(scene)

        print(
            f"\nMoved scene {scene} -> VAL "
            f"({len(records)} records, "
            f"{unknown_count} UNKNOWN)"
        )

    for scene, records, unknown_count in test_candidates:

        data["train"] = [
            r for r in data["train"]
            if scene_key(r) != scene
        ]

        data["test"].extend(records)

        moved_scenes.add(scene)

        print(
            f"\nMoved scene {scene} -> TEST "
            f"({len(records)} records, "
            f"{unknown_count} UNKNOWN)"
        )

    # ---------------------------------------------------------
    # Save
    # ---------------------------------------------------------

    for split, records in data.items():
        save(FILES[split], records)

    # ---------------------------------------------------------
    # Verify scene disjointness
    # ---------------------------------------------------------

    groups = {
        split: {
            scene_key(r)
            for r in records
        }
        for split, records in data.items()
    }

    tv = groups["train"] & groups["val"]
    tt = groups["train"] & groups["test"]
    vt = groups["val"] & groups["test"]

    print("\n" + "=" * 70)
    print("AFTER:")
    print("=" * 70)

    for split, records in data.items():
        print(split, stats(records))

    print("\nScene overlap:")
    print("train/val :", len(tv))
    print("train/test:", len(tt))
    print("val/test  :", len(vt))

    if tv or tt or vt:
        raise RuntimeError(
            "Scene leakage detected after rebalancing!"
        )

    print("\nDONE.")
    print("Original files backed up with:")
    print("*.before_unknown_rebalance.bak")


if __name__ == "__main__":
    main()