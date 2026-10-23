"""
SentinelAI — VLM Runtime V2

An independently testable VisualVerifier that:
- Loads Florence-2 exactly once (singleton pattern).
- Uses the correct dtype: float32 on CPU, float16 on CUDA.
- Explicitly logs whether the LoRA adapter was loaded or not.
- Returns structured VerificationResult objects.
- Handles all error conditions gracefully (invalid image, OOM, missing files).
- Never runs on every frame — only invoked on event-triggered keyframes.

This is V2 and lives in backend/vlm_runtime/.
V1 files in backend/vlm/ are PRESERVED and not modified.

Known regressions addressed:
  1. FP32-input / FP16-vision-weight mismatch: fixed by enforcing float32 on CPU.
  2. Encoder attention-mask shape mismatch: fixed by passing pixel_values
     explicitly and casting them to the model's dtype.
"""
from __future__ import annotations

import logging
import os
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

AnswerType = Literal["yes", "no", "unknown"]

LABELS: tuple[str, ...] = ("yes", "no", "unknown")


def normalize_answer(raw: str) -> AnswerType:
    """
    Map a model's free-text generation to one of yes / no / unknown.

    Identical normalization logic to V1 so comparisons are fair.
    """
    text = raw.strip().lower()
    if (
        text.startswith("unknown")
        or "cannot" in text
        or "not sure" in text
        or "insufficient" in text
    ):
        return "unknown"
    import re
    if re.search(r"\byes\b", text) and re.search(r"\bno\b", text):
        return "unknown"
    match = re.match(r"^(yes|no)\b", text)
    if match:
        return match.group(1)
    return "unknown"



@dataclass
class VerificationResult:
    """
    Structured result from a single VLM verification call.

    Attributes:
        answer:          Normalized answer: "yes", "no", or "unknown".
        raw_text:        Unmodified model output — useful for debugging.
        confidence:      Always None unless a calibrated method is implemented.
                         Do NOT fabricate confidence values.
        adapter_loaded:  True if a LoRA adapter was successfully applied.
        error:           Non-None if inference failed; answer will be "unknown".
    """
    answer: AnswerType
    raw_text: str
    confidence: float | None
    adapter_loaded: bool
    error: str | None = None
    task: str = "adapter_vqa"


# ---------------------------------------------------------------------------
# Prompt template (must match V1 so results are comparable)
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_TEMPLATE = "{question} Answer only with yes, no, or unknown."


# ---------------------------------------------------------------------------
# VisualVerifier
# ---------------------------------------------------------------------------

class VisualVerifier:
    """
    Florence-2 based visual verification for SentinelAI event candidates.

    The trained adapter answers yes/no/unknown questions about a still image.
    The public base model instead produces a supported detailed-caption task;
    its normalized presence answer remains unknown.
    It is designed to be invoked on event-triggered keyframes only, not
    on every frame from the camera.

    Args:
        base_model_id:    HuggingFace model ID or local path.
        adapter_dir:      Path to a PEFT/LoRA adapter directory.
                          If None or if the directory does not exist,
                          the base model is used and this is LOGGED EXPLICITLY.
        device:           "cpu", "cuda", or "auto" (picks cuda if available).
        max_new_tokens:   Generation budget (4 is sufficient for yes/no/unknown).
        prompt_template:  Must match the template used in training.
        enabled:          If False, all verify() calls return unknown immediately.
    """

    def __init__(
        self,
        base_model_id: str = "microsoft/Florence-2-base-ft",
        adapter_dir: str | None = None,
        device: str = "auto",
        max_new_tokens: int = 4,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.prompt_template = prompt_template
        self.max_new_tokens = max_new_tokens
        self._adapter_loaded: bool = False
        self._load_error: str | None = None

        if not enabled:
            logger.info("VLM VisualVerifier is DISABLED — all calls will return 'unknown'.")
            self._model = None
            self._processor = None
            self._torch = None
            self._device = "cpu"
            return

        self._device, self._dtype = self._resolve_device_dtype(device)
        self._torch = self._load_torch()
        self._model, self._processor, self._adapter_loaded = self._load_model(
            base_model_id, adapter_dir
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_device_dtype(device: str) -> tuple[str, object]:
        """
        Determine (device_str, torch_dtype).

        REGRESSION FIX: Florence-2's vision encoder uses float16 weights
        even when loaded in float32 mode on CPU, causing dtype mismatches.
        We enforce float32 on CPU unconditionally.
        """
        import torch

        if device == "auto":
            resolved = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            resolved = device

        # Enforce float32 on CPU to avoid the FP16/FP32 dtype mismatch.
        dtype = torch.float16 if resolved == "cuda" else torch.float32
        logger.info(
            "VLM device=%s  dtype=%s", resolved, dtype
        )
        return resolved, dtype

    @staticmethod
    def _load_torch():
        try:
            import torch
            return torch
        except ImportError as exc:
            raise RuntimeError(
                "torch is not installed. Install it to use the VLM verifier."
            ) from exc

    def _load_model(
        self, base_model_id: str, adapter_dir: str | None
    ) -> tuple[object, object, bool]:
        """
        Load Florence-2 base model, then optionally apply a LoRA adapter.

        Returns (model, processor, adapter_loaded).
        """
        from transformers import AutoModelForCausalLM, AutoProcessor

        torch = self._torch
        dtype = self._dtype

        logger.info("Loading Florence-2 base model: %s", base_model_id)
        try:
            try:
                model = AutoModelForCausalLM.from_pretrained(
                    base_model_id,
                    trust_remote_code=True,
                    torch_dtype=dtype,
                    attn_implementation="sdpa",
                )
            except Exception:
                # sdpa may not be available on all builds — fall back silently
                model = AutoModelForCausalLM.from_pretrained(
                    base_model_id,
                    trust_remote_code=True,
                    torch_dtype=dtype,
                )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load Florence-2 base model '{base_model_id}': {exc}"
            ) from exc

        try:
            processor = AutoProcessor.from_pretrained(
                base_model_id, trust_remote_code=True
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load Florence-2 processor for '{base_model_id}': {exc}"
            ) from exc

        adapter_loaded = False

        if adapter_dir is not None:
            adapter_path = Path(adapter_dir)
            if adapter_path.exists() and (adapter_path / "adapter_config.json").exists():
                try:
                    from peft import PeftModel
                    model = PeftModel.from_pretrained(model, str(adapter_path))
                    adapter_loaded = True
                    logger.info(
                        "✅ LoRA adapter loaded from: %s", adapter_path
                    )
                except Exception as exc:
                    logger.error(
                        "❌ Failed to load LoRA adapter from %s: %s. "
                        "Running base model only.",
                        adapter_path,
                        exc,
                    )
            else:
                logger.warning(
                    "❌ Adapter directory not found or missing adapter_config.json: %s. "
                    "Running base model only.",
                    adapter_dir,
                )
        else:
            logger.info(
                "No adapter_dir specified — running Florence-2 BASE MODEL ONLY. "
                "Expect lower accuracy for SentinelAI questions."
            )

        model = model.to(device=self._device, dtype=dtype).eval()

        logger.info(
            "Florence-2 loaded. adapter_loaded=%s  device=%s  dtype=%s",
            adapter_loaded,
            self._device,
            dtype,
        )
        return model, processor, adapter_loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        image,
        question: str,
    ) -> VerificationResult:
        """
        Run visual verification on an image.

        Args:
            image:    PIL.Image, uint8 HxWx3 numpy ndarray (BGR), or a path string/Path.
            question: A yes/no question about the visual content.

        Returns:
            VerificationResult with answer in {"yes", "no", "unknown"}.
        """
        if not self.enabled or self._model is None:
            return VerificationResult(
                answer="unknown",
                raw_text="",
                confidence=None,
                adapter_loaded=False,
                error="VLM is disabled.",
            )

        try:
            pil_image = self._to_pil(image)
        except Exception as exc:
            logger.error("VLM: failed to load image: %s", exc)
            return VerificationResult(
                answer="unknown",
                raw_text="",
                confidence=None,
                adapter_loaded=self._adapter_loaded,
                error=f"Image load error: {exc}",
            )

        try:
            return self._run_inference(pil_image, question)
        except Exception as exc:
            logger.error("VLM inference error: %s", exc)
            return VerificationResult(
                answer="unknown",
                raw_text="",
                confidence=None,
                adapter_loaded=self._adapter_loaded,
                error=f"Inference error: {exc}",
            )

    def describe(self, image) -> VerificationResult:
        """Caption with the base model, temporarily bypassing a presence adapter.

        Reuses the loaded model; the adapter is restored by its context manager.
        The managed worker serializes caption and verification requests.
        """
        if not self.is_ready:
            return VerificationResult("unknown", "", None, False, error="VLM is disabled.", task="<DETAILED_CAPTION>")
        try:
            context = self._model.disable_adapter() if self._adapter_loaded else nullcontext()
            with context:
                return self._run_inference(self._to_pil(image), "", descriptive=True)
        except Exception as exc:
            return VerificationResult("unknown", "", None, False, error=f"Caption inference error: {exc}", task="<DETAILED_CAPTION>")

    def _run_inference(self, pil_image, question: str, descriptive=False) -> VerificationResult:
        """Internal inference — only called with a valid PIL.Image."""
        torch = self._torch
        # The custom adapter was trained on yes/no questions. The public base
        # model supports task tokens, not arbitrary visual question answering.
        use_adapter = self._adapter_loaded and not descriptive
        task = "adapter_vqa" if use_adapter else "<DETAILED_CAPTION>"
        prompt = self.prompt_template.format(question=question.strip()) if use_adapter else task

        # Processor returns pixel_values, input_ids, attention_mask
        inputs = self._processor(
            text=prompt,
            images=pil_image,
            return_tensors="pt",
        )

        # Move all tensors to device
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        # REGRESSION FIX: pixel_values must match the model's weight dtype.
        # On CPU the model is float32; on CUDA it is float16.
        # The processor always returns float32, so we cast explicitly.
        if "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(self._dtype)

        with torch.no_grad():
            generated_ids = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs.get("pixel_values"),
                max_new_tokens=self.max_new_tokens if use_adapter else max(64, self.max_new_tokens),
                num_beams=1,
                do_sample=False,
            )

        raw_text = self._processor.batch_decode(
            generated_ids, skip_special_tokens=use_adapter
        )[0]

        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("Florence returned empty or malformed text")
        if not use_adapter:
            parsed = self._processor.post_process_generation(
                raw_text, task=task, image_size=pil_image.size)
            observation = parsed.get(task) if isinstance(parsed, dict) else None
            if not isinstance(observation, str) or not observation.strip():
                raise ValueError("Florence caption result is missing readable observations")
            raw_text = observation.strip()

        return VerificationResult(
            answer=normalize_answer(raw_text) if use_adapter else "unknown",
            raw_text=raw_text.strip(),
            confidence=None,  # not fabricated
            adapter_loaded=use_adapter,
            task=task,
        )

    # ------------------------------------------------------------------
    # Image conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_pil(image):
        """
        Convert various image types to PIL.Image (RGB).

        Accepts:
          - PIL.Image (returned as-is after converting to RGB)
          - numpy ndarray (assumes BGR from OpenCV; converts to RGB)
          - str / Path (opens with PIL)
        """
        from PIL import Image as PILImage

        if isinstance(image, PILImage.Image):
            return image.convert("RGB")

        if isinstance(image, (str, Path)):
            path = Path(image)
            if not path.exists():
                raise FileNotFoundError(f"Image file not found: {path}")
            with PILImage.open(path) as opened:
                opened.load()
                return opened.convert("RGB")

        if isinstance(image, np.ndarray):
            import cv2
            if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
                raise ValueError("Expected a nonempty uint8 HxWx3 BGR image")
            # OpenCV uses BGR — convert to RGB
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            return PILImage.fromarray(rgb)

        raise TypeError(
            f"Unsupported image type: {type(image).__name__}. "
            "Expected PIL.Image, numpy ndarray, or file path."
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def adapter_loaded(self) -> bool:
        return self._adapter_loaded

    @property
    def device(self) -> str:
        return self._device

    @property
    def is_ready(self) -> bool:
        return self.enabled and self._model is not None

    def __repr__(self) -> str:
        return (
            f"VisualVerifier(enabled={self.enabled}, "
            f"device={self._device!r}, "
            f"adapter_loaded={self._adapter_loaded})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_verifier_instance: VisualVerifier | None = None


def get_verifier(
    base_model_id: str = "microsoft/Florence-2-base-ft",
    adapter_dir: str | None = None,
    device: str = "auto",
    max_new_tokens: int = 4,
    enabled: bool = True,
    force_reload: bool = False,
) -> VisualVerifier:
    """
    Return (or create) the global VisualVerifier singleton.

    The model is loaded exactly once. Subsequent calls with the same
    parameters return the cached instance without re-loading.

    Args:
        force_reload: If True, discard any cached instance and reload.
    """
    global _verifier_instance
    if _verifier_instance is not None and not force_reload:
        return _verifier_instance

    _verifier_instance = VisualVerifier(
        base_model_id=base_model_id,
        adapter_dir=adapter_dir,
        device=device,
        max_new_tokens=max_new_tokens,
        enabled=enabled,
    )
    return _verifier_instance


def reset_verifier() -> None:
    """Discard the cached verifier — primarily for use in tests."""
    global _verifier_instance
    _verifier_instance = None
