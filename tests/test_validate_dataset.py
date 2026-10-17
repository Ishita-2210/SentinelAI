import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from training import validate_dataset


def record(image, answer="YES: visible.", scene=None):
    data = {
        "image": image,
        "detected_objects": ["person"],
        "question": "Is the person visible?",
        "answer": answer,
    }
    if scene:
        data["scene"] = scene
    return data


class ValidateDatasetTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "images").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **splits):
        for name, records in splits.items():
            for item in records:
                (self.root / "images" / item["image"]).touch()

            (self.root / f"{name}.jsonl").write_text(
                "\n".join(json.dumps(item) for item in records)
            )

    def validate(self):
        """Return (exit_code, output)."""
        out = io.StringIO()

        with mock.patch.object(sys, "argv", ["validate", str(self.root)]), \
                contextlib.redirect_stdout(out):
            try:
                validate_dataset.main()
                code = 0
            except SystemExit as exit_:
                code = exit_.code

        return code, out.getvalue()

    def test_valid_dataset(self):
        self.build(
            train=[record("a_001.jpg", scene="A"), record("a_002.jpg", "NO: empty.", scene="A")],
            val=[record("b_001.jpg", "UNKNOWN: occluded.", scene="B")],
            test=[record("c_001.jpg", scene="C")],
        )

        code, output = self.validate()

        self.assertEqual(code, 0, output)
        self.assertIn("OK", output)

    def test_scene_leakage_between_splits_fails(self):
        self.build(
            train=[record("a_001.jpg", scene="A")],
            val=[record("a_050.jpg", scene="A")],
            test=[record("c_001.jpg", scene="C")],
        )

        code, output = self.validate()

        self.assertEqual(code, 1)
        self.assertIn("scene leakage between train and val", output)

    def test_scene_inferred_from_filename_when_missing(self):
        # session1_001 and session1_002 are the same inferred scene.
        self.build(
            train=[record("session1_001.jpg")],
            val=[record("session1_002.jpg")],
            test=[record("session2_001.jpg")],
        )

        code, output = self.validate()

        self.assertEqual(code, 1)
        self.assertIn("scene leakage", output)

    def test_bad_answer_format_fails(self):
        self.build(
            train=[record("a_001.jpg", "The person is holding it.", scene="A")],
            val=[record("b_001.jpg", scene="B")],
            test=[record("c_001.jpg", scene="C")],
        )

        code, output = self.validate()

        self.assertEqual(code, 1)
        self.assertIn("answer must start with", output)

    def test_missing_image_fails(self):
        self.build(
            train=[record("a_001.jpg", scene="A")],
            val=[record("b_001.jpg", scene="B")],
            test=[record("c_001.jpg", scene="C")],
        )
        (self.root / "images" / "a_001.jpg").unlink()

        code, output = self.validate()

        self.assertEqual(code, 1)
        self.assertIn("image not found", output)

    def test_missing_train_file_fails_but_missing_test_only_warns(self):
        self.build(val=[record("b_001.jpg", scene="B")])

        code, output = self.validate()

        self.assertEqual(code, 1)
        self.assertIn("train.jsonl is missing", output)
        self.assertIn("test.jsonl is missing", output)

    def test_label_imbalance_warns(self):
        train = [record(f"a_{i:03d}.jpg", scene=f"S{i}") for i in range(30)]
        self.build(
            train=train,
            val=[record("b_001.jpg", scene="B")],
            test=[record("c_001.jpg", scene="C")],
        )

        code, output = self.validate()

        self.assertEqual(code, 0)
        self.assertIn("WARNING", output)


if __name__ == "__main__":
    unittest.main()
