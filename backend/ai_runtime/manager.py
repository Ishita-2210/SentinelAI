"""Shared bounded event/scene inference queue and direct local LLM lifecycle."""
import itertools
import hashlib
from pathlib import Path
import queue
import threading
import time
import copy
from datetime import datetime, timezone
from uuid import uuid4
from backend.ai_runtime.process import ModelProcess
from backend.llm.assistant import LLMAssistant
from backend.vlm_runtime.event_verifier import get_verification_question

class AIManager:
    def __init__(self,config,db):
        self.cfg,self.db=config,db
        self.vlm=ModelProcess("vlm",config.vlm.base_model_id,enabled=config.vlm.enabled,
            adapter_dir=str(config.resolve_path(config.vlm.adapter_dir)) if config.vlm.adapter_dir else None,
            runtime_path=str(config.resolve_path(config.vlm.runtime_path)) if config.vlm.runtime_path else None,
            timeout_s=config.vlm.timeout_s,load_timeout_s=config.vlm.load_timeout_s,
            max_new_tokens=config.vlm.max_new_tokens,cpu_threads=config.llm.cpu_threads)
        self.llm=LLMAssistant(config.llm)
        self._queue=queue.PriorityQueue(maxsize=config.vlm.queue_max_size)
        self._sequence=itertools.count()
        self._pending=set()
        self._lock=threading.Lock()
        self._stopped=threading.Event()
        self._thread=None
        self._scene = None

    def start(self):
        self.vlm.start();self.llm.start()
        if self.cfg.vlm.enabled:
            self._thread=threading.Thread(target=self._worker,name="event-vlm",daemon=True)
            self._thread.start()

    def snapshot(self):
        return dict(vlm=dict(self.vlm.snapshot(),queued=self._queue.qsize()),
                    llm=self.llm.snapshot())

    def scene_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._scene) if self._scene else {"state":"idle"}

    def enqueue_scene(self, jpeg, metadata):
        """Snapshot one real preview; share the existing bounded inference queue."""
        if not self.cfg.vlm.enabled:return "disabled", self.scene_snapshot()
        if self._stopped.is_set():return "stopped", self.scene_snapshot()
        if self.vlm.snapshot()["state"] == "error":return "error", self.scene_snapshot()
        with self._lock:
            if self._scene and self._scene["state"] in {"queued", "describing", "explaining"}:
                return "already_queued", copy.deepcopy(self._scene)
            if self._scene and self._scene["state"] == "completed" and self._scene.get("preview_sequence") == metadata.get("preview_sequence"):
                return "already_analyzed", copy.deepcopy(self._scene)
            if self._queue.full():return "queue_full", copy.deepcopy(self._scene)
            ident = uuid4().hex
            directory = self.cfg.resolve_path(self.cfg.evidence.output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ("scene_" + ident + ".jpg")
            path.write_bytes(jpeg)
            digest = hashlib.sha256(jpeg).hexdigest()
            self._scene = dict(metadata, id=ident, state="queued", caption_status="queued",
                               explanation_status="waiting", caption=None, explanation=None,
                               requested_at=datetime.now(timezone.utc).isoformat(),
                               evidence_url="/evidence/" + path.name, evidence_sha256=digest)
            # Manual/latest-scene work runs before additional automatic event checks.
            self._queue.put_nowait((-1,next(self._sequence),None,str(path),"Describe the visible scene.",digest))
            return "queued", copy.deepcopy(self._scene)

    def _update_scene(self, **values):
        with self._lock:
            self._scene.update(values)

    def _describe_scene(self, path, digest):
        try:
            self._update_scene(state="describing", caption_status="processing")
            started = time.perf_counter()
            result = self.vlm.request(dict(image_path=path, question="Describe the visible scene.",
                                          evidence_sha256=digest, task="caption"),wait_loading=True)
            caption = result.get("raw_text")
            if result.get("task") != "<DETAILED_CAPTION>" or not isinstance(caption,str) or not caption.strip():
                raise ValueError("Florence did not return a readable image description")
            if self._stopped.is_set():return
            self._update_scene(state="explaining", caption_status="completed", caption=caption.strip(),
                               caption_model=result.get("model_id"), caption_task=result["task"],
                               caption_ms=round((time.perf_counter()-started)*1000,1), explanation_status="processing")
            explanation = self.llm.explain("Explain what is visible in this frame in two concise sentences.", [],
                                           scene={"caption":caption.strip()})
            if self._stopped.is_set():return
            self._update_scene(state="completed", explanation=explanation["answer"],
                               explanation_status=explanation["generation_status"],
                               explanation_kind=explanation["answer_kind"], explanation_model=explanation.get("model"),
                               explanation_ms=explanation.get("inference_ms"), llm_used=explanation["llm_used"],
                               explanation_error=explanation.get("error"),
                               completed_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            if not self._stopped.is_set():
                self._update_scene(state="error", caption_status="error", error=str(exc), explanation_status="not_run")
        finally:
            if self._stopped.is_set():self._update_scene(state="cancelled", error="Application stopped before analysis finished")

    def enqueue_event(self,event_id,event_type,evidence_path,class_name=None,zone=None,force=False):
        if not self.cfg.vlm.enabled:return "disabled"
        if self._stopped.is_set():return "stopped"
        if not force and event_type not in self.cfg.vlm.event_types:return "not_selected"
        prompt=get_verification_question(event_type,class_name,zone)
        event = self.db.get_event_by_id(event_id)
        if event is None:
            return "event_missing"
        if event["evidence_path"] and evidence_path and Path(event["evidence_path"]).resolve() != Path(evidence_path).resolve():
            return "evidence_mismatch"
        if not evidence_path or not Path(evidence_path).is_file():
            self.db.set_verification(event_id,"error",prompt,self.cfg.vlm.base_model_id,error="Evidence image unavailable")
            return "evidence_missing"
        try:
            digest = hashlib.sha256(Path(evidence_path).read_bytes()).hexdigest()
        except OSError as exc:
            self.db.set_verification(event_id,"error",prompt,self.cfg.vlm.base_model_id,error=f"Evidence read failed: {exc}")
            return "evidence_missing"
        if not force and event["vlm_status"] == "inconclusive" and event["vlm_evidence_sha256"] == digest:
            return "already_verified"
        if self.vlm.snapshot()["state"]=="error":
            self.db.set_verification(event_id,"error",prompt,self.cfg.vlm.base_model_id,error=self.vlm.snapshot()["error"])
            return "error"
        with self._lock:
            if event_id in self._pending:return "already_queued"
            self._pending.add(event_id)
            self.db.set_verification(event_id,"queued",prompt,self.cfg.vlm.base_model_id)
            try:
                priority=0 if event_type=="UNATTENDED_OBJECT" else 1 if event_type=="LOITERING" else 2
                self._queue.put_nowait((priority,next(self._sequence),event_id,str(evidence_path),prompt,digest))
                return "queued"
            except queue.Full:
                self._pending.discard(event_id)
                self.db.set_verification(event_id,"skipped",prompt,self.cfg.vlm.base_model_id,error="Bounded VLM queue full")
                return "queue_full"

    def _worker(self):
        while not self._stopped.is_set():
            try:_,_,event_id,path,prompt,digest=self._queue.get(timeout=.2)
            except queue.Empty:continue
            if event_id is None:
                try:self._describe_scene(path,digest)
                finally:self._queue.task_done()
                continue
            try:
                self.db.set_verification(event_id,"processing",prompt,self.cfg.vlm.base_model_id)
                started = time.perf_counter()
                result=self.vlm.request(dict(image_path=path,question=prompt,evidence_sha256=digest),wait_loading=True)
                event = self.db.get_event_by_id(event_id)
                if event is None or (event["evidence_path"] and Path(event["evidence_path"]).resolve() != Path(path).resolve()):
                    raise ValueError("Event evidence association changed during inference")
                if not self._stopped.is_set():
                    # Answers are uncalibrated hypotheses, never a proof of temporal activity.
                    self.db.set_verification(event_id,"inconclusive",prompt,result["model_id"],
                        answer=result["answer"],raw_text=result["raw_text"],
                        adapter_loaded=result["adapter_loaded"],task=result.get("task","adapter_vqa"),
                        evidence_sha256=result.get("evidence_sha256",digest),
                        duration_ms=round((time.perf_counter()-started)*1000,1))
            except Exception as exc:
                if not self._stopped.is_set():
                    self.db.set_verification(event_id,"error",prompt,self.cfg.vlm.base_model_id,error=str(exc))
            finally:
                if self._stopped.is_set():
                    event=self.db.get_event_by_id(event_id)
                    if event and event["vlm_status"] in {"queued","processing"}:
                        self.db.set_verification(event_id,"cancelled",prompt,
                            self.cfg.vlm.base_model_id,error="Application stopped before verification completed")
                with self._lock:self._pending.discard(event_id)
                self._queue.task_done()

    def stop(self):
        self._stopped.set()
        self.vlm.stop();self.llm.stop()
        if self._thread:self._thread.join(timeout=5)
        with self._lock:
            if self._scene and self._scene["state"] in {"queued", "describing", "explaining"}:
                self._scene.update(state="cancelled", error="Application stopped before analysis finished")
            pending=list(self._pending)
            self._pending.clear()
        for event_id in pending:
            event=self.db.get_event_by_id(event_id)
            if event and event["vlm_status"] in {"queued","processing"}:
                self.db.set_verification(event_id,"cancelled",event["vlm_prompt"],
                    self.cfg.vlm.base_model_id,error="Application stopped before verification completed")
