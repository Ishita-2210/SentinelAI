
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.database.event_database import EventDatabase
from backend.llm.assistant import SYSTEM_PROMPT, Assistant
from backend.retrieval.retriever import EventRetriever
from tests.helpers import add_event


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class AssistantTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = EventDatabase(os.path.join(self.tmp.name, "e.db"))
        self.retriever = EventRetriever(self.database)

    def tearDown(self):
        self.database.close()
        self.tmp.cleanup()

    def test_no_events_never_calls_llm(self):
        assistant = Assistant(
            self.retriever, gemini_api_key="test-key"
        )

        with patch("urllib.request.urlopen") as mock_urlopen:
            result = assistant.ask("was there an unattended object?")

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["events"], [])
        self.assertIn("don't have any recorded events", result["answer"])
        mock_urlopen.assert_not_called()

    def test_llm_answer_is_grounded_in_retrieved_events(self):
        event_id = add_event(
            self.database, description="backpack unattended for 40s"
        )
        self.database.update_verification(
            event_id, "YES", "bag alone on floor"
        )

        reply = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": f"Yes, see [event {event_id}]."}
                        ]
                    }
                }
            ]
        }

        assistant = Assistant(
            self.retriever,
            gemini_api_key="test-key",
            model="test-model",
        )

        with patch(
            "urllib.request.urlopen", return_value=FakeResponse(reply)
        ) as mock_urlopen:
            result = assistant.ask("was there an unattended object?")

        self.assertTrue(result["llm_used"])
        self.assertEqual(result["answer"], f"Yes, see [event {event_id}].")

        request = mock_urlopen.call_args.args[0]
        self.assertIn(
            "/v1beta/models/test-model:generateContent", request.full_url
        )
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")

        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["system_instruction"]["parts"][0]["text"],
            SYSTEM_PROMPT,
        )

        user_prompt = payload["contents"][0]["parts"][0]["text"]
        self.assertIn(f"[event {event_id}]", user_prompt)
        self.assertIn("visual check: YES", user_prompt)
        self.assertIn(
            "QUESTION: was there an unattended object?", user_prompt
        )

    def test_falls_back_to_summary_when_llm_unreachable(self):
        event_id = add_event(self.database)
        assistant = Assistant(
            self.retriever,
            gemini_api_key="test-key",
            timeout=2,
        )

        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("simulated connection failure"),
        ):
            result = assistant.ask("was there an unattended object?")

        self.assertFalse(result["llm_used"])
        self.assertIn(f"[event {event_id}]", result["answer"])
        self.assertIn("visual check: not verified", result["answer"])

    def test_empty_llm_reply_falls_back(self):
        add_event(self.database)
        assistant = Assistant(
            self.retriever, gemini_api_key="test-key"
        )
        reply = {"candidates": [{"content": {"parts": [{"text": "   "}]}}]}

        with patch(
            "urllib.request.urlopen", return_value=FakeResponse(reply)
        ):
            result = assistant.ask("unattended object?")

        self.assertFalse(result["llm_used"])

    def test_llm_unavailable_without_api_key(self):
        assistant = Assistant(self.retriever)
        self.assertFalse(assistant.llm_available())

    def test_llm_available_when_key_configured(self):
        assistant = Assistant(
            self.retriever, gemini_api_key="test-key"
        )
        self.assertTrue(assistant.llm_available())

    def test_system_prompt_forbids_unsupported_claims(self):
        for phrase in (
            "ONLY the events",
            "not necessarily dangerous",
            "not have enough",
        ):
            self.assertIn(phrase, SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
