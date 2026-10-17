import unittest

from backend.vlm.vlm import (
    ANSWER_FORMAT,
    VisualVerifier,
    build_prompt,
    build_question,
    parse_verdict,
)


class ParseVerdictTests(unittest.TestCase):

    def test_well_formed(self):
        self.assertEqual(
            parse_verdict("YES: The person is holding the bottle."),
            ("YES", "The person is holding the bottle."),
        )
        self.assertEqual(parse_verdict("NO: hands are empty")[0], "NO")
        self.assertEqual(parse_verdict("UNKNOWN: object is occluded")[0], "UNKNOWN")

    def test_case_and_separator_variants(self):
        self.assertEqual(parse_verdict("yes - bag on floor"), ("YES", "bag on floor"))
        self.assertEqual(parse_verdict("  No: x")[0], "NO")

    def test_bare_verdict_gets_default_explanation(self):
        self.assertEqual(parse_verdict("YES"), ("YES", "No explanation given."))

    def test_anything_else_is_unknown_never_a_confirmation(self):
        for text in [
            "",
            None,
            "Maybe the person is holding something",
            "The bag appears to be unattended",
            "YESTERDAY the bag was here",
            "NOBODY is near the bag",
            "Yes, definitely",  # not the YES: contract
            "No one is holding the bag",  # a NO would suppress alerts
            "No clear view of the object",
            "Unknown object near the door",
        ]:
            verdict, _ = parse_verdict(text)
            self.assertEqual(verdict, "UNKNOWN", msg=repr(text))


class PromptTests(unittest.TestCase):

    def test_question_per_event_type(self):
        self.assertIn("backpack", build_question("UNATTENDED_OBJECT", "backpack"))
        self.assertIn("running", build_question("RUNNING", "person"))
        self.assertIn("bottle", build_question("SOMETHING_NEW", "bottle"))

    def test_prompt_contains_objects_question_and_format(self):
        prompt = build_prompt("Is it visible?", ["person", "bottle"])
        self.assertIn("person, bottle", prompt)
        self.assertIn("Is it visible?", prompt)
        self.assertIn(ANSWER_FORMAT, prompt)

        self.assertIn("unknown", build_prompt("q", None))


class VerifierFallbackTests(unittest.TestCase):

    def test_disabled_returns_unknown(self):
        result = VisualVerifier(enabled=False).verify_event(
            "UNATTENDED_OBJECT", "backpack", "missing.jpg"
        )
        self.assertEqual(result.verdict, "UNKNOWN")
        self.assertFalse(result.model_used)
        self.assertIn("disabled", result.explanation)

    def test_unloadable_model_returns_unknown_instead_of_raising(self):
        verifier = VisualVerifier(
            model_id="/nonexistent/florence-model", enabled=True
        )

        result = verifier.verify_event("LOITERING", "person", "missing.jpg")

        self.assertEqual(result.verdict, "UNKNOWN")
        self.assertFalse(result.model_used)
        self.assertFalse(verifier.available)
        self.assertIsNotNone(verifier.load_error)

        # A failed load is attempted once, not on every event.
        verifier.verify_event("LOITERING", "person", "missing.jpg")


if __name__ == "__main__":
    unittest.main()
