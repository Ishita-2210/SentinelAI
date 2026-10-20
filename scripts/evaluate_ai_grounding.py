"""Opt-in real local inference over synthetic records and an operator-supplied image.

Does not open cameras/serial or download models. Reports contract properties,
not an accuracy score. Production event stores are never modified.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ai_runtime.manager import AIManager
from backend.ai_runtime.process import ModelUnavailable
from backend.config.settings import Settings
from backend.database.event_database import EventDatabase
from backend.retrival.retrival import EventRetriever
from backend.schemas.event import Event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--base", action="store_true", help="Explicit base Florence caption evaluation; no weight change")
    parser.add_argument("--output", type=Path, default=ROOT / "data/integration/grounding_evaluation.json")
    args = parser.parse_args()
    image = args.image.resolve()
    if not image.is_file():
        parser.error("--image must be an existing authorized local image")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cfg = Settings()
    cfg.vlm.enabled = cfg.llm.enabled = True
    if args.base:
        cfg.vlm.adapter_dir = None
    report = {"status": "failed", "records": "synthetic evaluation only", "real_local_inference": True,
              "base_requested": args.base, "checks": []}
    with tempfile.TemporaryDirectory(prefix="grounding_", dir=args.output.parent) as directory:
        db = EventDatabase(str(Path(directory) / "events.db"))
        ai = AIManager(cfg, db)
        try:
            ai.start()
            deadline = time.monotonic() + 200
            while time.monotonic() < deadline:
                states = [model["state"] for model in ai.snapshot().values()]
                if "error" in states:
                    raise RuntimeError(str(ai.snapshot()))
                if all(state == "ready" for state in states):
                    break
                time.sleep(.2)
            assert all(model["state"] == "ready" for model in ai.snapshot().values()), ai.snapshot()
            ident = db.save_event(Event("LOITERING", 7, "person", datetime.now(timezone.utc),
                zone="synthetic-zone", description="Synthetic duration rule record; not a physical incident."), str(image))
            assert ai.enqueue_event(ident, "LOITERING", str(image), "person") == "queued"
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                row = EventRetriever(db).get_by_id(ident)
                if row["vlm_status"] in {"inconclusive", "error"}:
                    break
                time.sleep(.1)
            assert row["vlm_status"] == "inconclusive", row
            assert row["vlm_evidence_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
            assert row["vlm_raw_text"] and not row["vlm_error"]
            if args.base:
                assert row["vlm_task"] == "<DETAILED_CAPTION>" and row["vlm_answer"] == "unknown"
            report["visual_result"] = row
            report["checks"].append("real VLM output attached to synthetic event and exact supplied image hash")
            cases = [("valid", "Show event #" + str(ident), [row]),
                     ("missing_image", "What evidence is available?", [dict(row, evidence_path=None,
                         vlm_raw_text=None, vlm_answer=None, vlm_status=None)]),
                     ("conflicting_metadata", "What happened?", [dict(row, vlm_status="error",
                         vlm_error="Synthetic image failure", vlm_raw_text="stale output")]),
                     ("unavailable_fact", "Who is this person and what is their intent?", [row])]
            report["qa"] = {}
            for name, question, records in cases:
                answer = ai.llm.query(question, records)
                assert answer["llm_used"] and answer["generation_status"] == "validated", answer
                assert answer["source_event_ids"] == [ident]
                assert "cannot be established" in answer["answer"]
                if name == "missing_image": assert "no saved image reference" in answer["answer"]
                if name == "conflicting_metadata": assert "stale output" not in answer["answer"]
                report["qa"][name] = answer
                report["checks"].append(name)
            before = ai.llm.snapshot()["inference_count"]
            empty = ai.llm.query("Any matching records?", [])
            assert empty["generation_status"] == "no_evidence" and not empty["llm_used"]
            assert ai.llm.snapshot()["inference_count"] == before
            report["checks"].append("empty retrieval skips inference and does not invent an event")
            corrupt = Path(directory) / "corrupt.jpg"
            corrupt.write_bytes(b"deliberately corrupt evaluation input")
            child = ai.vlm._proc
            try:
                ai.vlm.request(dict(image_path=str(corrupt), question="Visible?"))
                raise AssertionError("Corrupt image succeeded")
            except ModelUnavailable:
                assert ai.vlm.snapshot()["state"] == "ready"
            retried = ai.vlm.request(dict(image_path=str(image), question="Is a person visible?"))
            assert retried["raw_text"] and ai.vlm._proc is child
            report["checks"].append("corrupt image fails; valid image retries in same loaded worker")
            report.update(status="passed", models=ai.snapshot())
        except Exception as exc:
            report.update(error=str(exc), models=ai.snapshot())
        finally:
            ai.stop()
            db.close()
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": report["checks"], "error": report.get("error"),
                      "report": str(args.output)}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
