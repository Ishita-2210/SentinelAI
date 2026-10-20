import json
import re
import shutil
from pathlib import Path

# ============================================================
# YOUR PROJECT STRUCTURE
# D:\SentinelAI\backend\vlm\fix_dataset.py
# D:\SentinelAI\dataset\images\
# D:\SentinelAI\dataset\train.jsonl
# D:\SentinelAI\dataset\val.jsonl
# D:\SentinelAI\dataset\test.jsonl
# ============================================================

DATA_DIR = Path(r"..\..\dataset").resolve()
IMAGE_DIR = DATA_DIR / "images"

SPLITS = ["train", "val", "test"]

VALID_ANSWERS = {"yes", "no", "unknown"}


# ============================================================
# ANSWER NORMALIZATION
# Converts:
#   "YES: The person is holding the pen."
#   "NO: no."
#   "UNKNOWN: not enough evidence."
# into:
#   "yes"
#   "no"
#   "unknown"
# ============================================================

def normalize_answer(value):
    if value is None:
        return None

    # Handle VQAv2-style answer lists
    if isinstance(value, list):
        values = [
            str(v).strip()
            for v in value
            if str(v).strip()
        ]

        if not values:
            return None

        value = values[0]

    text = str(value).strip().lower()

    # Exact answer
    if text in VALID_ANSWERS:
        return text

    # YES: ...
    # NO: ...
    # UNKNOWN: ...
    match = re.match(
        r"^(yes|no|unknown)\s*(?::|-|\.)?",
        text
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# GET FIRST AVAILABLE FIELD
# ============================================================

def get_first(record, *keys):
    for key in keys:
        if key in record:
            value = record[key]

            if value is not None and str(value).strip() != "":
                return value

    return None


# ============================================================
# BUILD IMAGE INDEX ONCE
# ============================================================

def build_image_index():
    index = {}

    if not IMAGE_DIR.exists():
        raise FileNotFoundError(
            f"Image directory not found:\n{IMAGE_DIR}"
        )

    for path in IMAGE_DIR.rglob("*"):
        if not path.is_file():
            continue

        name = path.name.lower()
        stem = path.stem.lower()

        index[name] = path
        index[stem] = path

    return index


# ============================================================
# FIND IMAGE
#
# Supports things like:
#   test1.png
#   test1
#   vqav2_393243_393243002.jpg
#   393243
# ============================================================

def find_image(image_id, image_path, image_index):

    candidates = []

    # --------------------------------------------------------
    # 1. image_path directly
    # --------------------------------------------------------

    if image_path:
        p = Path(str(image_path).replace("\\", "/"))

        candidates.append(p.name.lower())
        candidates.append(p.stem.lower())

    # --------------------------------------------------------
    # 2. image_id directly
    # --------------------------------------------------------

    if image_id is not None:
        image_id_str = str(image_id).strip()

        candidates.append(image_id_str.lower())

        p = Path(image_id_str)

        candidates.append(p.name.lower())
        candidates.append(p.stem.lower())

        # COCO-style zero padding
        if image_id_str.isdigit():
            padded = image_id_str.zfill(12)
            candidates.append(padded.lower())

    # --------------------------------------------------------
    # Exact filename / stem match
    # --------------------------------------------------------

    for candidate in candidates:
        if candidate in image_index:
            return image_index[candidate]

    # --------------------------------------------------------
    # Partial match
    #
    # Example:
    # image_id = 393243
    # actual file = vqav2_393243_393243002.jpg
    # --------------------------------------------------------

    if image_id is not None:

        image_id_str = str(image_id).strip().lower()

        for name, path in image_index.items():

            if image_id_str in name:
                return path

    return None


# ============================================================
# NORMALIZE ONE RECORD
# ============================================================

def normalize_record(record, split, index, image_index):

    # --------------------------------------------------------
    # QUESTION
    # --------------------------------------------------------

    question = get_first(
        record,
        "question",
        "question_text",
        "text"
    )

    if question is None:
        raise ValueError(
            f"record {index}: missing question"
        )

    # --------------------------------------------------------
    # ANSWER
    # --------------------------------------------------------

    raw_answer = get_first(
        record,
        "answer",
        "label",
        "target"
    )

    answer = normalize_answer(raw_answer)

    if answer is None:
        raise ValueError(
            f"record {index}: invalid answer {raw_answer!r}"
        )

    # --------------------------------------------------------
    # IMAGE ID
    # --------------------------------------------------------

    image_id = get_first(
        record,
        "image_id",
        "imageId",
        "img_id"
    )

    # --------------------------------------------------------
    # IMAGE PATH
    # --------------------------------------------------------

    image_path = get_first(
        record,
        "image_path",
        "file_name",
        "filename",
        "image_file"
    )

    # --------------------------------------------------------
    # Sometimes "image" contains either:
    #   - filename
    #   - image id
    # --------------------------------------------------------

    raw_image = record.get("image")

    if image_path is None and isinstance(raw_image, str):

        raw_image_clean = raw_image.strip()

        # Looks like a file path
        if (
            "." in Path(raw_image_clean).name
            or "/" in raw_image_clean
            or "\\" in raw_image_clean
        ):
            image_path = raw_image_clean

            if image_id is None:
                image_id = Path(raw_image_clean).stem

        # Otherwise treat as image_id
        elif image_id is None:
            image_id = raw_image_clean

    # --------------------------------------------------------
    # VQAv2 question_id fallback
    # --------------------------------------------------------

    if image_id is None:

        question_id = get_first(
            record,
            "question_id",
            "qid"
        )

        if question_id is not None:
            image_id = str(question_id)

    # --------------------------------------------------------
    # FIND ACTUAL IMAGE
    # --------------------------------------------------------

    image_file = find_image(
        image_id=image_id,
        image_path=image_path,
        image_index=image_index
    )

    if image_file is None:

        raise ValueError(
            f"record {index} ({image_id}): "
            f"could not find corresponding image in "
            f"{IMAGE_DIR}"
        )

    # --------------------------------------------------------
    # If image_id is missing, derive it from filename
    # --------------------------------------------------------

    if image_id is None:
        image_id = image_file.stem

    # --------------------------------------------------------
    # SCENE ID
    #
    # Existing scene_id is preserved.
    #
    # Otherwise:
    # one image = one scene
    #
    # This keeps multiple questions for the same image
    # in the same logical scene.
    # --------------------------------------------------------

    scene_id = get_first(
        record,
        "scene_id"
    )

    if scene_id is None:
        scene_id = f"scene_{image_file.stem}"

    # --------------------------------------------------------
    # IMAGE PATH RELATIVE TO dataset/
    # --------------------------------------------------------

    image_path_relative = str(
        image_file.relative_to(DATA_DIR)
    ).replace("\\", "/")

    # --------------------------------------------------------
    # OUTPUT RECORD
    # --------------------------------------------------------

    output = {
        "image_id": str(image_id),
        "scene_id": str(scene_id),
        "image_path": image_path_relative,
        "question": str(question).strip(),
        "answer": answer
    }

    # Preserve optional fields
    relation = get_first(record, "relation")
    difficulty = get_first(record, "difficulty")
    notes = get_first(record, "notes")

    if relation is not None:
        output["relation"] = relation

    if difficulty is not None:
        output["difficulty"] = difficulty

    if notes is not None:
        output["notes"] = notes

    return output


# ============================================================
# PROCESS TRAIN / VAL / TEST
# ============================================================

def process_split(split, image_index):

    source_file = DATA_DIR / f"{split}.jsonl"
    backup_file = DATA_DIR / f"{split}.jsonl.bak"

    if not source_file.exists():
        raise FileNotFoundError(
            f"Missing split file:\n{source_file}"
        )

    records = []
    errors = []

    # --------------------------------------------------------
    # READ JSONL
    # --------------------------------------------------------

    with source_file.open(
        "r",
        encoding="utf-8"
    ) as f:

        for line_number, line in enumerate(f):

            line = line.strip()

            if not line:
                continue

            try:

                record = json.loads(line)

                fixed_record = normalize_record(
                    record,
                    split,
                    line_number,
                    image_index
                )

                records.append(fixed_record)

            except Exception as e:

                errors.append(
                    f"record {line_number}: {e}"
                )

    # --------------------------------------------------------
    # REPORT ERRORS
    # --------------------------------------------------------

    if errors:

        print()
        print("=" * 70)
        print(f"{split}.jsonl: {len(errors)} unresolved record(s)")
        print("=" * 70)

        for error in errors[:50]:
            print(" -", error)

        if len(errors) > 50:
            print(
                f" ... and {len(errors) - 50} more"
            )

        return False

    # --------------------------------------------------------
    # BACKUP ORIGINAL
    # --------------------------------------------------------

    if not backup_file.exists():

        shutil.copy2(
            source_file,
            backup_file
        )

    # --------------------------------------------------------
    # WRITE FIXED FILE
    # --------------------------------------------------------

    with source_file.open(
        "w",
        encoding="utf-8"
    ) as f:

        for record in records:

            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False
                )
                + "\n"
            )

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    yes_count = sum(
        r["answer"] == "yes"
        for r in records
    )

    no_count = sum(
        r["answer"] == "no"
        for r in records
    )

    unknown_count = sum(
        r["answer"] == "unknown"
        for r in records
    )

    scene_count = len(
        set(r["scene_id"] for r in records)
    )

    print(
        f"{split}: fixed {len(records)} records"
    )

    print(
        f"       yes={yes_count} "
        f"no={no_count} "
        f"unknown={unknown_count} "
        f"scenes={scene_count}"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("SentinelAI VLM Dataset Fixer")
    print("=" * 70)

    print()
    print("Dataset :", DATA_DIR)
    print("Images  :", IMAGE_DIR)

    # --------------------------------------------------------
    # CHECK DATASET
    # --------------------------------------------------------

    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"Dataset directory does not exist:\n{DATA_DIR}"
        )

    if not IMAGE_DIR.exists():
        raise FileNotFoundError(
            f"Image directory does not exist:\n{IMAGE_DIR}"
        )

    # --------------------------------------------------------
    # INDEX ALL IMAGES
    # --------------------------------------------------------

    print()
    print("Indexing images...")

    image_index = build_image_index()

    print(
        f"Indexed {len(image_index)} image references."
    )

    # --------------------------------------------------------
    # PROCESS ALL SPLITS
    # --------------------------------------------------------

    results = []

    for split in SPLITS:

        success = process_split(
            split,
            image_index
        )

        results.append(success)

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    print()
    print("=" * 70)

    if all(results):

        print("DATASET FIX COMPLETE")
        print("=" * 70)

        print()
        print("Backups created:")
        print("  train.jsonl.bak")
        print("  val.jsonl.bak")
        print("  test.jsonl.bak")

        print()
        print("Your dataset now uses:")
        print('  answer: "yes" / "no" / "unknown"')

        print()
        print("Image paths now look like:")
        print('  "images/test1.png"')
        print('  "images/vqav2_393243_393243002.jpg"')

        print()
        print("NEXT:")
        print("Run the VLM trainer with --dry_run.")

    else:

        print("DATASET STILL HAS UNRESOLVED RECORDS")
        print("=" * 70)

        print()
        print(
            "The unresolved records printed above need "
            "manual inspection."
        )


if __name__ == "__main__":
    main()