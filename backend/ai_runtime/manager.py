"""Event-triggered VLM queue and direct local LLM lifecycle."""
import itertools
import hashlib
from pathlib import Path
import queue
import threading
import time
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

    def start(self):
        self.vlm.start();self.llm.start()
        if self.cfg.vlm.enabled:
            self._thread=threading.Thread(target=self._worker,name="event-vlm",daemon=True)
            self._thread.start()

    def snapshot(self):
        return dict(vlm=dict(self.vlm.snapshot(),queued=self._queue.qsize()),
                    llm=self.llm.snapshot())

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
            pending=list(self._pending)
            self._pending.clear()
        for event_id in pending:
            event=self.db.get_event_by_id(event_id)
            if event and event["vlm_status"] in {"queued","processing"}:
                self.db.set_verification(event_id,"cancelled",event["vlm_prompt"],
                    self.cfg.vlm.base_model_id,error="Application stopped before verification completed")
