"""Manual VLM check.

Usage:
    python -m backend.vlm.test_vlm path/to/keyframe.jpg [event_type] [object]

Prints the verdict for one keyframe. Without a fine-tuned LoRA adapter
(SENTINEL_VLM_ADAPTER) the base model usually does not follow the
YES/NO/UNKNOWN format, so expect UNKNOWN.
"""

import sys

from backend.config.settings import get_settings
from backend.vlm.vlm import VisualVerifier


def main():

    if len(sys.argv) < 2:
        print(__doc__)
        return

    image_path = sys.argv[1]
    event_type = sys.argv[2] if len(sys.argv) > 2 else "UNATTENDED_OBJECT"
    class_name = sys.argv[3] if len(sys.argv) > 3 else "backpack"

    settings = get_settings()

    verifier = VisualVerifier(
        model_id=settings.vlm_model_id,
        adapter_path=settings.vlm_adapter_path,
        enabled=settings.vlm_enabled,
    )

    result = verifier.verify_event(event_type, class_name, image_path)

    print(f"Verdict    : {result.verdict}")
    print(f"Explanation: {result.explanation}")
    print(f"Model used : {result.model_used}")

    if result.raw:
        print(f"Raw output : {result.raw}")


if __name__ == "__main__":
    main()
