"""Synthetic records/images and mocked inference; no physical hardware or weights."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from backend.config.settings import LLMConfig, Settings
from backend.llm.assistant import LLMAssistant
from backend.schemas.event import Event
from backend.vlm_runtime.verifier import VisualVerifier
from tests.test_local_ai import FakeModel, fixture_rows
from tests.test_presentation import launcher_root


@pytest.mark.parametrize("frame", [np.zeros((0, 2, 3), dtype=np.uint8),
    np.zeros((2, 2), dtype=np.uint8), np.zeros((2, 2, 3), dtype=np.float32)])
def test_invalid_vlm_and_tracker_images_are_rejected(frame):
    from backend.tracker.tracker import Tracker
    with pytest.raises(ValueError): VisualVerifier._to_pil(frame)
    with pytest.raises(ValueError): Tracker._validate_frame(frame)


def test_vlm_bgr_conversion_and_detached_file(tmp_path):
    frame = np.zeros((4, 5, 3), dtype=np.uint8)
    frame[:, :, 2] = 255
    assert VisualVerifier._to_pil(frame).getpixel((0, 0)) == (255, 0, 0)
    path = tmp_path / "image.png"
    Image.fromarray(frame).save(path)
    loaded = VisualVerifier._to_pil(path)
    path.unlink()
    assert loaded.size == (5, 4)


@pytest.mark.parametrize("adapter", [False, True])
def test_florence_task_and_parsing_use_actual_model_mode(adapter):
    calls = {}
    class Tensor:
        def to(self, device): return self
    class Processor:
        def __call__(self, **kwargs):
            calls.update(kwargs)
            return {"input_ids": Tensor(), "pixel_values": Tensor()}
        def batch_decode(self, *args, **kwargs):
            return ["yes" if adapter else "<s>A person beside a table.</s>"]
        def post_process_generation(self, text, task, image_size):
            calls["parsed_task"] = task
            return {task: "A person beside a table."}
    verifier = VisualVerifier(enabled=False)
    verifier._adapter_loaded = adapter
    verifier._device = "cpu"
    verifier._dtype = "float32"
    verifier._torch = SimpleNamespace(no_grad=nullcontext)
    verifier._processor = Processor()
    verifier._model = SimpleNamespace(generate=lambda **kwargs: calls.update(generation=kwargs))
    result = verifier._run_inference(Image.new("RGB", (20, 10)), "Is a person visible?")
    assert result.answer == ("yes" if adapter else "unknown")
    assert result.task == ("adapter_vqa" if adapter else "<DETAILED_CAPTION>")
    assert calls["text"] == ("Is a person visible? Answer only with yes, no, or unknown."
                              if adapter else "<DETAILED_CAPTION>")
    if not adapter:
        assert result.raw_text == "A person beside a table."
        assert calls["generation"]["max_new_tokens"] == 64


def test_corrupt_image_is_error_not_success(tmp_path):
    verifier = VisualVerifier(enabled=False)
    verifier.enabled = True
    verifier._model = object()
    image = tmp_path / "bad.jpg"
    image.write_bytes(b"not an image")
    result = verifier.verify(image, "Is a person visible?")
    assert result.answer == "unknown" and result.error.startswith("Image load error:")


def test_inference_exception_is_error(monkeypatch):
    verifier = VisualVerifier(enabled=False)
    verifier.enabled = True
    verifier._model = object()
    def fail(*args): raise RuntimeError("synthetic inference failure")
    monkeypatch.setattr(verifier, "_run_inference", fail)
    assert "synthetic inference failure" in verifier.verify(Image.new("RGB", (4, 4)), "Visible?").error


def test_keyframe_collision_cannot_overwrite_evidence(tmp_path):
    from backend.evidence.keyframe_capture import KeyframeCapture
    capture = KeyframeCapture(str(tmp_path))
    stamp = datetime.now(timezone.utc)
    paths = [capture.save(np.zeros((4, 4, 3), dtype=np.uint8), "LOITERING", 1, stamp) for _ in range(2)]
    assert paths[0] != paths[1] and all(Path(p).is_file() for p in paths)
    with pytest.raises(ValueError): capture.save(None, "../escape", 1, stamp)


def test_event_evidence_mismatch_never_queues(tmp_db, tmp_path):
    from backend.ai_runtime.manager import AIManager
    cfg = Settings(); cfg.vlm.enabled = True
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(b"synthetic a"); b.write_bytes(b"synthetic b")
    ident = tmp_db.save_event(Event("LOITERING", 1, "person", datetime.now(timezone.utc)), str(a))
    manager = AIManager(cfg, tmp_db)
    assert manager.enqueue_event(ident, "LOITERING", str(b)) == "evidence_mismatch"
    assert manager._queue.empty()


def test_caption_provenance_roundtrips_all_retrievals(tmp_db):
    from backend.retrival.retrival import EventRetriever
    stamp = datetime.now(timezone.utc)
    ident = tmp_db.save_event(Event("LOITERING", 1, "person", stamp, description="fixture"))
    tmp_db.set_verification(ident, "inconclusive", "Visible?", "fixture-model", "unknown", "A person.",
                            False, task="<DETAILED_CAPTION>", evidence_sha256="a" * 64)
    retriever = EventRetriever(tmp_db)
    rows = [retriever.get_by_id(ident), retriever.get_recent()[0], retriever.get_by_type("LOITERING")[0],
            retriever.search("fixture")[0], retriever.for_question("event #" + str(ident))[0][0]]
    assert all(row["vlm_evidence_sha256"] == "a" * 64 for row in rows)
    assert all("caption" in row["vlm_scope"] for row in rows)


def test_qa_supplies_only_matching_bounded_context_and_marks_unknowns():
    class Capture(FakeModel):
        def request(self, payload):
            self.payload = payload
            return super().request(payload)
    model = Capture()
    rows = fixture_rows()
    rows[0].update(vlm_status="inconclusive", vlm_raw_text="A person.", vlm_task="<DETAILED_CAPTION>")
    result = LLMAssistant(LLMConfig(context_event_limit=1), service=model).query("Who is this and why?", rows)
    context = model.payload["context_events"]
    assert [e["id"] for e in context] == [1]
    assert context[0]["visual_observation"] == "A person."
    assert context[0]["evidence_available"] is False
    assert "cannot be established" in result["answer"]
    assert "no saved image reference" in result["answer"]


def test_qa_error_metadata_does_not_supply_old_visual_output():
    class Capture(FakeModel):
        def request(self, payload):
            assert payload["context_events"][0]["visual_observation"] is None
            raise RuntimeError("synthetic model failure")
    rows = fixture_rows()
    rows[0].update(vlm_raw_text="stale caption", vlm_status="error", vlm_error="corrupt image")
    result = LLMAssistant(LLMConfig(), service=Capture()).query("What happened?", rows)
    assert result["generation_status"] == "error"
    assert "stale caption" not in result["answer"]
    assert result["source_event_ids"] == [1]


def test_state_and_event_memory_expire_after_track_loss():
    from backend.state_manager.state_manager import StateManager
    from backend.event_engine.event_engine import EventEngine
    from tests.test_event_engine import _make_track, _run_frame, T0
    sm, engine = StateManager(), EventEngine()
    _run_frame(sm, engine, [_make_track(1, 100, 100, 200, 300)], T0)
    _run_frame(sm, engine, [], T0 + timedelta(seconds=2))
    _run_frame(sm, engine, [], T0 + timedelta(seconds=31))
    assert not sm.states and not engine._last_seen and not engine._entered


def test_default_launcher_is_full_ai_webcam(launcher_root):
    from scripts.presentation import prepare
    result = prepare()
    assert result["source"] == "0" and result["source_kind"] == "webcam"
    assert "--vlm" in result["command"] and "--llm" in result["command"]


def test_context_budget_drops_whole_records_and_preserves_question():
    import json
    from backend.ai_runtime.worker import prepare_llm_inputs
    calls = []
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs): return json.dumps(messages)
        def __call__(self, text, **kwargs):
            assert kwargs["truncation"] is False
            calls.append(text)
            return {"input_ids": SimpleNamespace(shape=(1, len(text)))}
    context = [{"id": 1, "description": "a" * 100}, {"id": 2, "description": "b" * 100}]
    request = dict(messages=[{"role": "system", "content": "Rules"},
        {"role": "user", "content": "Events: " + json.dumps(context) + "\nQuestion: final-question"}],
        context_events=context, question="final-question", allowed_event_ids=[1, 2])
    inputs, allowed = prepare_llm_inputs(Tokenizer(), request, max_tokens=260)
    assert inputs["input_ids"].shape[1] <= 260 and allowed == [1]
    assert "final-question" in calls[-1] and "Rules" in calls[-1]
    assert 'b' * 100 not in calls[-1]
    assert len(context) == 2  # Caller records are preserved.


def test_oversized_question_is_explicit_error_without_truncation():
    from backend.ai_runtime.worker import prepare_llm_inputs
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs): return "huge"
        def __call__(self, text, **kwargs): return {"input_ids": SimpleNamespace(shape=(1, 2000))}
    with pytest.raises(ValueError, match="context budget"):
        prepare_llm_inputs(Tokenizer(), dict(messages=[], context_events=[]))


def test_invalid_caption_structure_is_a_failure():
    class Tensor:
        def to(self, *args): return self
    class Processor:
        def __call__(self, **kwargs): return {"input_ids": Tensor()}
        def batch_decode(self, *args, **kwargs): return ["generated"]
        def post_process_generation(self, *args, **kwargs): return {"<OD>": {"bboxes": []}}
    verifier = VisualVerifier(enabled=False)
    verifier.enabled = True
    verifier._torch = SimpleNamespace(no_grad=nullcontext)
    verifier._processor = Processor()
    verifier._model = SimpleNamespace(generate=lambda **kwargs: [])
    result = verifier.verify(Image.new("RGB", (4, 4)), "Visible?")
    assert result.answer == "unknown" and "missing readable observations" in result.error


def test_completed_identical_evidence_skips_automatic_duplicate(tmp_db, tmp_path):
    import hashlib
    from backend.ai_runtime.manager import AIManager
    cfg = Settings(); cfg.vlm.enabled = True
    image = tmp_path / "image.jpg"; image.write_bytes(b"synthetic image")
    ident = tmp_db.save_event(Event("LOITERING", 1, "person", datetime.now(timezone.utc)), str(image))
    tmp_db.set_verification(ident, "inconclusive", "Visible?", "fixture", "yes", "yes", True,
                           evidence_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    ai = AIManager(cfg, tmp_db)
    assert ai.enqueue_event(ident, "LOITERING", str(image)) == "already_verified"
    assert ai.enqueue_event(ident, "LOITERING", str(image), force=True) == "queued"


def test_absolute_evidence_paths_normalize_before_containment_check(tmp_path):
    cfg = Settings(project_root=tmp_path)
    root = tmp_path / "events"
    escaped = cfg.resolve_path(str(root / ".." / "outside.jpg"))
    assert not escaped.is_relative_to(root)
