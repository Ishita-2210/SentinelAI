"""One model per managed subprocess, bounded requests, truthful lifecycle."""
from concurrent.futures import Future, TimeoutError as FutureTimeout
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]

class ModelUnavailable(RuntimeError): pass
class ModelBusy(RuntimeError): pass

class ModelProcess:
    def __init__(self, kind, model_id, enabled=False, adapter_dir=None, runtime_path=None,
                 timeout_s=60, load_timeout_s=180, max_new_tokens=96, cpu_threads=2):
        self.kind, self.model_id, self.enabled = kind, model_id, enabled
        self.config = dict(kind=kind, model_id=model_id, adapter_dir=adapter_dir,
                           runtime_path=runtime_path, max_new_tokens=max_new_tokens,
                           cpu_threads=cpu_threads)
        self.timeout_s, self.load_timeout_s = timeout_s, load_timeout_s
        self._state = "disabled" if not enabled else "loading"
        self._error = None
        self._meta = {}
        self._proc = None
        self._ready = threading.Event()
        self._request_lock = threading.Lock()
        self._pending = {}
        self._counter = 0
        self._stopping = False
        self._log = None
        self._timer = None
        self._reader = None
        self._last_inference_error = None
        self._inference_count = 0
        self._last_inference_at = None
        self._last_inference_ms = None

    def snapshot(self):
        return dict(state=self._state, enabled=self.enabled, model_id=self.model_id,
                    error=self._error, last_inference_error=self._last_inference_error,
                    busy=self._request_lock.locked(), local_only=True,
                    inference_count=self._inference_count, last_inference_at=self._last_inference_at,
                    last_inference_ms=self._last_inference_ms,
                    **self._meta)

    def start(self):
        if not self.enabled or self._reader is not None:
            return
        self._reader = threading.Thread(target=self._run, name=self.kind+"-model", daemon=True)
        self._reader.start()

    def _fail(self, message):
        if self._stopping:
            return
        self._state, self._error = "error", str(message)
        self._ready.set()
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ModelUnavailable(str(message)))

    def _loading_expired(self):
        if self._state == "loading":
            self._fail("Model loading exceeded "+str(self.load_timeout_s)+" seconds; restart to retry")
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def _run(self):
        try:
            logdir = ROOT/"data/logs"
            logdir.mkdir(parents=True, exist_ok=True)
            self._log = (logdir/(self.kind+"-worker.log")).open("a", encoding="utf-8")
            env = os.environ.copy()
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS=str(self.config["cpu_threads"]),
                       MKL_NUM_THREADS=str(self.config["cpu_threads"]), PYTHONIOENCODING="utf-8")
            self._proc = subprocess.Popen(
                [sys.executable, "-B", "-u", str(ROOT/"backend/ai_runtime/worker.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                text=True, encoding="utf-8", bufsize=1, cwd=ROOT, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._proc.stdin.write(json.dumps(self.config)+"\n"); self._proc.stdin.flush()
            self._timer = threading.Timer(self.load_timeout_s, self._loading_expired)
            self._timer.daemon = True; self._timer.start()
            for line in self._proc.stdout:
                try: msg = json.loads(line)
                except ValueError: continue
                if msg.get("type") == "ready":
                    if self._state != "error" and not self._stopping:
                        self._meta = msg.get("meta", {})
                        self._state, self._error = "ready", None
                        self._ready.set()
                        self._timer.cancel()
                elif msg.get("type") == "load_error":
                    self._fail(msg.get("error", "Model loading failed"))
                elif msg.get("type") == "result":
                    future = self._pending.get(msg.get("id"))
                    if future and not future.done():
                        future.set_result(msg)
            if not self._stopping and self._state != "error":
                self._fail("Model worker exited; inspect data/logs/"+self.kind+"-worker.log")
        except Exception as exc:
            self._fail(exc)
        finally:
            if self._timer:
                self._timer.cancel()
            if self._proc:
                try: self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired: self._proc.kill(); self._proc.wait(timeout=2)
            if self._log:
                self._log.close()

    def request(self, payload, wait_loading=False):
        if wait_loading and self._state == "loading":
            self._ready.wait(self.load_timeout_s+1)
        if self._state != "ready":
            raise ModelUnavailable(self._error or self.kind.upper()+" is "+self._state)
        if not self._request_lock.acquire(blocking=False):
            raise ModelBusy(self.kind.upper()+" already has an inference request")
        try:
            started = time.perf_counter()
            self._counter += 1
            ident = self._counter
            future = Future()
            self._pending[ident] = future
            self._proc.stdin.write(json.dumps(dict(id=ident, **payload))+"\n")
            self._proc.stdin.flush()
            try:
                result = future.result(timeout=self.timeout_s)
            except FutureTimeout:
                self._fail("Inference exceeded "+str(self.timeout_s)+" seconds; restart to retry")
                self._proc.terminate()
                raise ModelUnavailable(self._error)
            if result.get("error"):
                self._last_inference_error = result["error"]
                # A bad image/request does not unload a healthy worker. Keep
                # timeouts/process exits fatal, but permit corrected evidence retry.
                raise ModelUnavailable("Inference failed: "+result["error"])
            self._last_inference_error = None
            self._inference_count += 1
            self._last_inference_at = time.time()
            self._last_inference_ms = round((time.perf_counter() - started) * 1000, 1)
            return result["data"]
        finally:
            self._pending.pop(locals().get("ident"), None)
            self._request_lock.release()

    def stop(self):
        self._stopping = True
        self._ready.set()
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ModelUnavailable("Application stopping"))
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try: self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired: self._proc.kill(); self._proc.wait(timeout=2)
        if self._reader:
            self._reader.join(timeout=4)
        self._state = "disabled"
