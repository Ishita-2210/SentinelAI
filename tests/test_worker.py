import os
import tempfile
import unittest

from backend.database.event_database import EventDatabase
from backend.services.alert_service import AlertService
from backend.services.verification_worker import (
    VerificationJob,
    VerificationWorker,
)
from backend.vlm.vlm import VLMResult
from tests.helpers import add_event


class FakeVerifier:
    def __init__(self, verdict, explanation="because"):
        self.result = VLMResult(verdict, explanation)
        self.calls = []

    def verify_event(self, event_type, class_name, image_path, detected_objects=None):
        self.calls.append((event_type, class_name, image_path))
        return self.result


class WorkerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "e.db")
        self.database = EventDatabase(self.path)

    def tearDown(self):
        self.database.close()
        self.tmp.cleanup()

    def run_job(self, verifier, event_id, event_type, evidence_path="x.jpg"):
        worker = VerificationWorker(
            self.path, verifier, AlertService(cooldown_sec=0)
        )
        worker.start()
        worker.submit(VerificationJob(event_id, event_type, "backpack", evidence_path))
        worker.stop()  # drains the queue, then stops

        return self.database.get_event(event_id)

    def test_confirmed_event_is_stored_and_alerted(self):
        event_id = add_event(self.database, "UNATTENDED_OBJECT")
        verifier = FakeVerifier("YES", "bag alone on floor")

        row = self.run_job(verifier, event_id, "UNATTENDED_OBJECT")

        self.assertEqual(row["verification"], "YES")
        self.assertEqual(row["verification_detail"], "bag alone on floor")
        self.assertEqual(row["alerted"], 1)
        self.assertEqual(verifier.calls, [("UNATTENDED_OBJECT", "backpack", "x.jpg")])

    def test_contradicted_event_is_stored_but_not_alerted(self):
        event_id = add_event(self.database, "UNATTENDED_OBJECT")

        row = self.run_job(
            FakeVerifier("NO", "a person is holding the bag"),
            event_id,
            "UNATTENDED_OBJECT",
        )

        self.assertEqual(row["verification"], "NO")
        self.assertEqual(row["alerted"], 0)

    def test_unknown_still_alerts_because_engine_is_primary(self):
        event_id = add_event(self.database, "LOITERING", class_name="person")

        row = self.run_job(FakeVerifier("UNKNOWN"), event_id, "LOITERING")

        self.assertEqual(row["verification"], "UNKNOWN")
        self.assertEqual(row["alerted"], 1)

    def test_no_evidence_skips_vlm_but_still_alerts(self):
        event_id = add_event(self.database, "UNATTENDED_OBJECT")
        verifier = FakeVerifier("YES")

        row = self.run_job(verifier, event_id, "UNATTENDED_OBJECT", evidence_path=None)

        self.assertIsNone(row["verification"])
        self.assertEqual(verifier.calls, [])
        self.assertEqual(row["alerted"], 1)

    def test_verifier_exception_does_not_kill_worker(self):
        class Exploding(FakeVerifier):
            def verify_event(self, *args, **kwargs):
                raise RuntimeError("boom")

        first = add_event(self.database, "UNATTENDED_OBJECT")
        second = add_event(self.database, "LOITERING", class_name="person")

        worker = VerificationWorker(
            self.path, Exploding("YES"), AlertService(cooldown_sec=0)
        )
        worker.start()
        worker.submit(VerificationJob(first, "UNATTENDED_OBJECT", "backpack", "x.jpg"))
        worker.submit(VerificationJob(second, "LOITERING", "person", None))
        worker.stop()

        # Second job (no evidence, so no VLM call) was still processed.
        self.assertEqual(self.database.get_event(second)["alerted"], 1)

    def test_full_queue_drops_instead_of_blocking(self):
        worker = VerificationWorker(
            self.path, FakeVerifier("YES"), AlertService(), max_queue=1
        )
        # Worker thread not started, so nothing drains the queue.
        job = VerificationJob(1, "LOITERING", "person", None)

        self.assertTrue(worker.submit(job))
        self.assertFalse(worker.submit(job))


if __name__ == "__main__":
    unittest.main()
