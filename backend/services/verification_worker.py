"""Background worker: VLM verification + alerts.

VLM inference takes seconds on CPU, so it must never block the real-time
detection loop. The pipeline enqueues a job per important event and this
thread verifies it, stores the verdict, and then raises any alert.
"""

import logging
import queue
import threading
from dataclasses import dataclass

from backend.database.event_database import EventDatabase
from backend.services.alert_service import AlertService
from backend.vlm.vlm import VisualVerifier

logger = logging.getLogger(__name__)

_STOP = object()


@dataclass
class VerificationJob:
    event_id: int
    event_type: str
    class_name: str
    evidence_path: str | None


class VerificationWorker:

    def __init__(
        self,
        database_path: str,
        verifier: VisualVerifier,
        alerts: AlertService,
        max_queue: int = 32,
    ):
        self.database_path = database_path
        self.verifier = verifier
        self.alerts = alerts

        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(
            target=self._run,
            name="verification-worker",
            daemon=True,
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._queue.put(_STOP)
        self._thread.join(timeout=10)

    def submit(self, job: VerificationJob) -> bool:
        """Queue a job. Returns False (and drops it) if the queue is full."""

        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            logger.warning("Verification queue full, dropping event %s", job.event_id)
            return False

    def _run(self):

        # SQLite connections are bound to their thread: open our own.
        database = EventDatabase(self.database_path)

        try:
            while True:
                job = self._queue.get()

                if job is _STOP:
                    break

                try:
                    self._process(database, job)
                except Exception:  # noqa: BLE001 - keep the worker alive
                    logger.exception("Verification failed for event %s", job.event_id)
        finally:
            database.close()

    def _process(self, database: EventDatabase, job: VerificationJob):

        verdict = None

        if job.evidence_path:
            result = self.verifier.verify_event(
                job.event_type,
                job.class_name,
                job.evidence_path,
            )

            verdict = result.verdict

            database.update_verification(
                job.event_id,
                result.verdict,
                result.explanation,
            )

            print(
                f"VERIFY: event {job.event_id} -> {result.verdict} "
                f"({result.explanation})"
            )

        alert = self.alerts.handle(job.event_type, verdict)

        if alert.sent:
            database.mark_alerted(job.event_id)
            print(f"ALERT: event {job.event_id} ({alert.reason})")
