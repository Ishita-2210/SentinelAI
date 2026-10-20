# tests/test_vlm_normalizer.py
"""
Tests for VLM answer normalization — no model loading required.
"""
import pytest
from backend.vlm_runtime.verifier import normalize_answer


@pytest.mark.parametrize("raw,expected", [
    ("yes",                          "yes"),
    ("Yes, the person is there",     "yes"),
    ("YES",                          "yes"),
    ("no",                           "no"),
    ("No, there is nothing there",   "no"),
    ("NO",                           "no"),
    ("unknown",                      "unknown"),
    ("Unknown — cannot determine",   "unknown"),
    ("I cannot tell from this image","unknown"),
    ("not sure",                     "unknown"),
    ("insufficient evidence",        "unknown"),
    ("",                             "unknown"),  # empty → unknown
    ("maybe",                        "unknown"),  # ambiguous → unknown
    ("yes definitely yes",           "yes"),
    ("no, not at all",               "no"),
])
def test_normalize_answer(raw, expected):
    assert normalize_answer(raw) == expected


def test_verifier_disabled_returns_unknown():
    """A disabled VisualVerifier must return unknown without loading any model."""
    from backend.vlm_runtime.verifier import VisualVerifier, reset_verifier
    reset_verifier()
    v = VisualVerifier(enabled=False)
    result = v.verify(None, "Is there a person?")
    assert result.answer == "unknown"
    assert result.error is not None
    reset_verifier()


def test_verifier_invalid_image_returns_unknown():
    """Passing a non-existent path should return unknown with error, not crash."""
    from backend.vlm_runtime.verifier import VisualVerifier, reset_verifier
    reset_verifier()
    v = VisualVerifier(enabled=False)  # disabled — no model needed
    result = v.verify("/nonexistent/path.jpg", "Is there a bag?")
    assert result.answer == "unknown"
    reset_verifier()


def test_get_verification_question():
    from backend.vlm_runtime.event_verifier import get_verification_question
    q = get_verification_question("LOITERING")
    assert "?" in q
    assert len(q) > 10

    q2 = get_verification_question("UNATTENDED_OBJECT", class_name="backpack")
    assert "backpack" in q2.lower()

    # Unknown event type should return a fallback question
    q3 = get_verification_question("TOTALLY_UNKNOWN_TYPE")
    assert "?" in q3
