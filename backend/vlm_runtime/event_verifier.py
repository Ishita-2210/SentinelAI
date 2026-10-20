"""
SentinelAI — Event-triggered VLM verification

Maps SentinelAI event types to meaningful verification questions,
and runs the VLM asynchronously in a background thread so the
real-time detection loop is never blocked by expensive inference.

Design:
  - EventVerifier owns a background worker thread.
  - Events are enqueued when detected. The thread dequeues, runs VLM,
    and calls the result_callback with (event_id, result).
  - The queue has a max size; oldest entries are dropped when full to
    prevent memory build-up during heavy event periods.
  - The verifier can be disabled; in that case the queue is ignored.

Usage:
    def on_result(event_id: int, result: VerificationResult) -> None:
        db.update_vlm_result(event_id, result.answer, result.raw_text)

    ev = EventVerifier(verifier=get_verifier(...), result_callback=on_result)
    ev.start()

    # ... in your main loop after detecting an event:
    ev.enqueue(event_id=42, event_type="UNATTENDED_OBJECT",
               image=frame, class_name="backpack", zone="entrance")

    ev.stop()
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from backend.vlm_runtime.verifier import VerificationResult, VisualVerifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event-type → verification question mapping
# ---------------------------------------------------------------------------

# Questions must be answerable by the model with yes / no / unknown
# based on a single still keyframe.
_EVENT_QUESTIONS: dict[str, str] = {
    "PERSON_ENTERED": "Is a person visible in the image?",
    "PERSON_EXITED": "Is a person visible in the image?",
    "ZONE_CHANGED": "Is a person visible in the image?",
    "LOITERING": "Is a person visible in the image?",
    "RUNNING": "Is a person visible in the image?",
    "UNATTENDED_OBJECT": "Is a bag or portable object visible in the image?",
}

_DEFAULT_QUESTION = "Is there any suspicious or unusual activity visible?"


def get_verification_question(
    event_type: str,
    class_name: str | None = None,
    zone: str | None = None,
) -> str:
    """
    Build a natural-language verification question for an event.

    Args:
        event_type:  SentinelAI event type string.
        class_name:  YOLO class name of the relevant object.
        zone:        Zone name where the event occurred.

    Returns:
        A yes/no question suitable for Florence-2.
    """
    question = _EVENT_QUESTIONS.get(event_type, _DEFAULT_QUESTION)

    # Optionally personalise the question with class/zone context
    if event_type == "UNATTENDED_OBJECT" and class_name:
        question = (
            f"Is a {class_name} visible in the image?"
        )
    return question


# ---------------------------------------------------------------------------
# Verification task
# ---------------------------------------------------------------------------

@dataclass
class _VerificationTask:
    event_id: int
    event_type: str
    image: object      # PIL.Image, ndarray, or path
    class_name: str | None
    zone: str | None


# ---------------------------------------------------------------------------
# EventVerifier
# ---------------------------------------------------------------------------

class EventVerifier:
    """
    Asynchronous wrapper that runs VLM verification on a background thread.

    Args:
        verifier:        A VisualVerifier instance (already loaded).
        result_callback: Called on the worker thread with (event_id, result).
                         Keep it fast — it runs on the VLM thread.
        queue_max_size:  Maximum number of pending tasks.
    """

    def __init__(
        self,
        verifier: VisualVerifier,
        result_callback: Callable[[int, VerificationResult], None],
        queue_max_size: int = 8,
    ) -> None:
        self._verifier = verifier
        self._callback = result_callback
        self._queue: queue.Queue[_VerificationTask | None] = queue.Queue(
            maxsize=queue_max_size
        )
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            name="vlm-verifier",
            daemon=True,
        )
        self._thread.start()
        logger.info("EventVerifier worker thread started.")

    def stop(self, timeout_s: float = 5.0) -> None:
        """Signal the worker to stop and wait for it to finish."""
        if not self._running:
            return
        self._running = False
        try:
            self._queue.put_nowait(None)  # sentinel
        except queue.Full:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        logger.info("EventVerifier worker thread stopped.")

    def enqueue(
        self,
        event_id: int,
        event_type: str,
        image: object,
        class_name: str | None = None,
        zone: str | None = None,
    ) -> bool:
        """
        Submit a verification task.

        Returns True if enqueued, False if the queue was full (task dropped).
        """
        if not self._verifier.enabled:
            return False

        task = _VerificationTask(
            event_id=event_id,
            event_type=event_type,
            image=image,
            class_name=class_name,
            zone=zone,
        )
        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            logger.warning(
                "VLM queue full — dropping verification for event_id=%d (%s).",
                event_id,
                event_type,
            )
            return False

    def _worker(self) -> None:
        """Background thread: dequeue tasks and run VLM inference."""
        logger.info("VLM worker running.")
        while self._running:
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if task is None:  # stop sentinel
                break

            question = get_verification_question(
                task.event_type, task.class_name, task.zone
            )
            logger.debug(
                "VLM verifying event_id=%d  type=%s  question=%r",
                task.event_id,
                task.event_type,
                question,
            )

            result = self._verifier.verify(task.image, question)
            logger.info(
                "VLM result: event_id=%d  answer=%s  adapter_loaded=%s",
                task.event_id,
                result.answer,
                result.adapter_loaded,
            )

            try:
                if self._running:
                    self._callback(task.event_id, result)
            except Exception as exc:
                logger.error(
                    "VLM result_callback raised: %s", exc, exc_info=True
                )

        logger.info("VLM worker exiting.")
