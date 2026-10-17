"""Florence-2 visual evidence verifier.

The deterministic event engine decides *that* something happened. The VLM
only answers a narrow, focused question about the captured keyframe and is
allowed to say UNKNOWN. It never invents events.

Output contract (matches the fine-tuning target):

    YES: <short visible evidence>
    NO: <short visible evidence>
    UNKNOWN: <why the image is insufficient>

Anything that cannot be parsed into that contract is treated as UNKNOWN,
so a base (un-fine-tuned) model degrades to "not verified" instead of
producing unsupported claims.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

VERDICTS = ("YES", "NO", "UNKNOWN")

# The verdict must be followed by a separator (":" or a dash) or be the
# whole answer. Free text that merely starts with a verdict word, such as
# "No clear view of the object", is NOT a NO: a NO suppresses alerts.
_VERDICT_PATTERN = re.compile(
    r"^\s*(YES|NO|UNKNOWN)\s*(?:[:\-–—]\s*(.*)|)$",
    re.IGNORECASE | re.DOTALL,
)

ANSWER_FORMAT = (
    "Answer with YES, NO or UNKNOWN followed by a short reason "
    "based only on what is visible. Use UNKNOWN if the image does "
    "not show enough evidence."
)

# Focused question per event type. {obj} is the detected object class.
EVENT_QUESTIONS = {
    "UNATTENDED_OBJECT": (
        "Is the {obj} visibly separated from any person, with nobody "
        "visibly holding or touching it?"
    ),
    "LOITERING": "Is the person visibly staying in the same area?",
    "RUNNING": "Is the person visibly running?",
    "PERSON_ENTERED": "Is a person visible in the scene?",
    "PERSON_EXITED": "Is the person no longer clearly visible in the scene?",
    "ZONE_CHANGED": "Is a person visible in the scene?",
}

DEFAULT_QUESTION = "Is the {obj} visible in the scene?"


@dataclass
class VLMResult:
    verdict: str  # YES / NO / UNKNOWN
    explanation: str
    raw: str = ""
    model_used: bool = True

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "explanation": self.explanation,
            "model_used": self.model_used,
        }


def parse_verdict(text: str) -> tuple[str, str]:
    """Parse model output into (verdict, explanation).

    Unparseable output becomes UNKNOWN. This is deliberate: a missing or
    malformed answer must never count as a confirmation.
    """

    cleaned = (text or "").strip()

    match = _VERDICT_PATTERN.match(cleaned)

    if not match:
        return "UNKNOWN", "Model output did not follow the YES/NO/UNKNOWN format."

    verdict = match.group(1).upper()
    explanation = (match.group(2) or "").strip() or "No explanation given."

    return verdict, explanation


def build_question(event_type: str, class_name: str) -> str:
    template = EVENT_QUESTIONS.get(event_type, DEFAULT_QUESTION)
    return template.format(obj=class_name)


def build_prompt(
    question: str,
    detected_objects: list[str] | None = None,
) -> str:
    """Prompt layout shared by inference and training.

    Keeping this in one place guarantees the fine-tuned model sees at
    inference the same text format it was trained on.
    """

    objects = ", ".join(detected_objects) if detected_objects else "unknown"

    return (
        f"Detected objects: {objects}. "
        f"Question: {question} "
        f"{ANSWER_FORMAT}"
    )


class VisualVerifier:
    """Lazy-loading Florence-2 wrapper with an optional LoRA adapter."""

    def __init__(
        self,
        model_id: str = "microsoft/Florence-2-base-ft",
        adapter_path: str = "",
        enabled: bool = True,
        device: str | None = None,
        max_new_tokens: int = 64,
    ):
        self.model_id = model_id
        self.adapter_path = adapter_path
        self.enabled = enabled
        self.device = device
        self.max_new_tokens = max_new_tokens

        self._model = None
        self._processor = None
        self._load_attempted = False
        self.load_error: str | None = None

    # ---------------------------------
    # Loading
    # ---------------------------------

    @property
    def available(self) -> bool:
        """True when the model is loaded and usable."""
        if not self.enabled:
            return False
        self._load()
        return self._model is not None

    def _load(self):

        if self._load_attempted:
            return

        self._load_attempted = True

        if not self.enabled:
            return

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor

            device = self.device or (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
            dtype = torch.float16 if device == "cuda" else torch.float32

            model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                torch_dtype=dtype,
                trust_remote_code=True,
            )

            if self.adapter_path:
                from peft import PeftModel

                if not Path(self.adapter_path).exists():
                    raise FileNotFoundError(
                        f"LoRA adapter not found: {self.adapter_path}"
                    )

                model = PeftModel.from_pretrained(
                    model,
                    self.adapter_path,
                )

            self._model = model.to(device).eval()
            self._processor = AutoProcessor.from_pretrained(
                self.model_id,
                trust_remote_code=True,
            )
            self.device = device

            logger.info(
                "VLM loaded: %s (adapter=%s, device=%s)",
                self.model_id,
                self.adapter_path or "none",
                device,
            )

        except Exception as error:  # noqa: BLE001 - any load failure disables the VLM
            self.load_error = f"{type(error).__name__}: {error}"
            self._model = None
            self._processor = None
            logger.warning("VLM unavailable: %s", self.load_error)

    # ---------------------------------
    # Inference
    # ---------------------------------

    def ask(
        self,
        image_path: str,
        question: str,
        detected_objects: list[str] | None = None,
    ) -> VLMResult:
        """Ask one focused question about one keyframe."""

        if not self.available:
            reason = (
                "VLM disabled."
                if not self.enabled
                else f"VLM unavailable ({self.load_error})."
            )
            return VLMResult(
                verdict="UNKNOWN",
                explanation=reason,
                model_used=False,
            )

        try:
            import torch
            from PIL import Image

            image = Image.open(image_path).convert("RGB")
            prompt = build_prompt(question, detected_objects)

            inputs = self._processor(
                text=prompt,
                images=image,
                return_tensors="pt",
            ).to(self.device)

            if self.device == "cuda":
                inputs["pixel_values"] = inputs["pixel_values"].half()

            with torch.no_grad():
                generated = self._model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=self.max_new_tokens,
                    num_beams=3,
                    do_sample=False,
                )

            raw = self._processor.batch_decode(
                generated,
                skip_special_tokens=True,
            )[0]

        except Exception as error:  # noqa: BLE001
            logger.warning("VLM inference failed: %s", error)
            return VLMResult(
                verdict="UNKNOWN",
                explanation=f"VLM inference failed ({type(error).__name__}).",
                model_used=False,
            )

        verdict, explanation = parse_verdict(raw)

        return VLMResult(
            verdict=verdict,
            explanation=explanation,
            raw=raw,
        )

    def verify_event(
        self,
        event_type: str,
        class_name: str,
        image_path: str,
        detected_objects: list[str] | None = None,
    ) -> VLMResult:
        """Verify one detected event against its captured keyframe."""

        question = build_question(event_type, class_name)

        return self.ask(
            image_path,
            question,
            detected_objects or [class_name],
        )
