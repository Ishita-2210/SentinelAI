"""
SentinelAI Florence-2 visual-verification inference — fully standalone,
single file, zero sibling-file imports.

Use this after training (train_lora_standalone.py) to call the model
from your Event Engine as a visual-verification step: YOLO11n +
ByteTrack + the State Manager decide THAT a candidate event happened;
this only confirms WHAT it was.

Example:
    from verify_standalone import VisualVerifier
    verifier = VisualVerifier(adapter_dir="adapters/sentinel-vqa-v1/best")
    result = verifier.verify(cropped_frame, "Is the person holding the bag?")
    # {"answer": "yes"/"no"/"unknown", "raw_text": "..."}

Command-line smoke test (after training, or even against the raw base
model with no adapter to sanity-check the model loads):
    python verify_standalone.py --image some.jpg --question "Is the person holding the bag?"
    python verify_standalone.py --image some.jpg --question "..." --adapter_dir adapters/sentinel-vqa-v1/best

Needs torch, transformers, peft, Pillow (see requirements.txt). There
is no --dry_run here since inference inherently needs the model.
"""
from __future__ import annotations
import argparse

LABELS = ("yes", "no", "unknown")

# Must match the prompt_template used in train_lora_standalone.py.
DEFAULT_PROMPT_TEMPLATE = "{question} Answer only with yes, no, or unknown."


def normalize_answer(raw: str) -> str:
    text = raw.strip().lower()
    if text.startswith("unknown") or "cannot" in text or "not sure" in text or "insufficient" in text:
        return "unknown"
    if text.startswith("yes"):
        return "yes"
    if text.startswith("no"):
        return "no"
    if "unknown" in text:
        return "unknown"
    if "yes" in text and "no" not in text:
        return "yes"
    if "no" in text and "yes" not in text:
        return "no"
    return "unknown"


class VisualVerifier:
    def __init__(
        self,
        base_model_id: str = "microsoft/Florence-2-base-ft",
        adapter_dir: str | None = None,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        device: str | None = None,
    ):
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.prompt_template = prompt_template
        self._torch = torch

        dtype = torch.float16 if self.device == "cuda" else torch.float32
        try:
            model = AutoModelForCausalLM.from_pretrained(
                base_model_id, trust_remote_code=True, torch_dtype=dtype, attn_implementation="sdpa",
            )
        except Exception:
            model = AutoModelForCausalLM.from_pretrained(base_model_id, trust_remote_code=True, torch_dtype=dtype)
        processor = AutoProcessor.from_pretrained(base_model_id, trust_remote_code=True)

        if adapter_dir:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter_dir)
            print(f"Loaded LoRA adapter from {adapter_dir}")
        else:
            print("No adapter_dir given — running the base model as-is (expect poor accuracy).")

        self.model = model.to(self.device).eval()
        self.processor = processor

    def verify(self, image, question: str, max_new_tokens: int = 4) -> dict:
        torch = self._torch
        prompt = self.prompt_template.format(question=question.strip())
        inputs = self.processor(text=prompt, images=image, return_tensors="pt").to(self.device)

        with torch.no_grad():
            generated = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, num_beams=1, do_sample=False
            )
        raw_text = self.processor.batch_decode(generated, skip_special_tokens=True)[0]
        return {"answer": normalize_answer(raw_text), "raw_text": raw_text.strip()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="path to an image file")
    ap.add_argument("--question", required=True)
    ap.add_argument("--base_model_id", default="microsoft/Florence-2-base-ft")
    ap.add_argument("--adapter_dir", default=None)
    args = ap.parse_args()

    from PIL import Image
    image = Image.open(args.image).convert("RGB")

    verifier = VisualVerifier(base_model_id=args.base_model_id, adapter_dir=args.adapter_dir)
    result = verifier.verify(image, args.question)
    print(result)


if __name__ == "__main__":
    main()
