
"""Natural-language interface over verified event history.

Flow: question -> retrieval -> grounded prompt -> Gemini API.

Multiple API keys are supported. Rate-limited keys are temporarily
cooled down, and the next eligible key is tried.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request

from backend.retrieval.retriever import EventRetriever

logger = logging.getLogger(__name__)

KEY_COOLDOWN_SECONDS = 60

SYSTEM_PROMPT = (
    "You are SentinelAI's assistant. You answer questions about events "
    "recorded by a camera monitoring system.\n"
    "Rules:\n"
    "1. Use ONLY the events listed under EVENTS. Never add details that "
    "are not in them.\n"
    "2. If the events do not answer the question, say you do not have "
    "enough recorded evidence.\n"
    "3. 'visual check' shows whether a vision model confirmed the event: "
    "YES = confirmed, NO = contradicted, UNKNOWN or NOT_VERIFIED = not "
    "confirmed. Mention it when it matters, and never present an "
    "unconfirmed event as certain.\n"
    "4. Do not infer intent, identity or danger. An unattended object is "
    "not necessarily dangerous.\n"
    "5. Refer to events by their [event N] id and keep answers short."
)


class Assistant:

    def __init__(
        self,
        retriever: EventRetriever,
        gemini_api_key: str = "",
        model: str = "gemini-2.5-flash",
        timeout: float = 30.0,
        gemini_api_keys: list[str] | None = None,
        **legacy_options,
    ):
        self.retriever = retriever
        self.model = model
        self.timeout = timeout

        # Support both the old single-key argument and the new key list.
        supplied_keys = list(gemini_api_keys or [])
        if gemini_api_key:
            supplied_keys.append(gemini_api_key)

        # Remove duplicates and empty values while preserving key order.
        self.api_keys = list(
            dict.fromkeys(key.strip() for key in supplied_keys if key.strip())
        )

        # Compatibility for older callers; Ollama is not used.
        self._legacy_ollama_url = legacy_options.get("ollama_url")

        self._key_index = 0
        self._key_retry_after: dict[str, float] = {}
        self._key_lock = threading.Lock()

    # ---------------------------------
    # Public API
    # ---------------------------------

    def ask(self, question: str, limit: int = 8) -> dict:
        events = self.retriever.search(question, limit=limit)

        if not events:
            return {
                "answer": (
                    "I don't have any recorded events that match that "
                    "question."
                ),
                "events": [],
                "llm_used": False,
            }

        context = self.retriever.format_context(events)
        answer = self._call_llm(question, context)

        if answer is None:
            return {
                "answer": self.summarize(events),
                "events": events,
                "llm_used": False,
            }

        return {
            "answer": answer,
            "events": events,
            "llm_used": True,
        }

    @staticmethod
    def summarize(events: list[dict]) -> str:
        """Build a deterministic summary when Gemini is unavailable."""
        lines = [f"Found {len(events)} matching event(s):"]

        for event in events:
            verification = event.get("verification") or "not verified"
            lines.append(
                f"- [event {event['id']}] {event['timestamp']}: "
                f"{event['event_type']} ({event['class_name']}, "
                f"zone {event['zone']}), visual check: {verification}."
            )

        return "\n".join(lines)

    def llm_available(self) -> bool:
        """Return whether at least one API key is configured."""
        return bool(self.api_keys)

    # ---------------------------------
    # Key selection and cooldown
    # ---------------------------------

    def _keys_to_try(self) -> list[str]:
        """Return eligible keys in round-robin order."""
        with self._key_lock:
            if not self.api_keys:
                return []

            now = time.monotonic()
            count = len(self.api_keys)
            start = self._key_index
            ordered = [
                self.api_keys[(start + offset) % count]
                for offset in range(count)
            ]

            # Advance the starting position for the next request.
            self._key_index = (start + 1) % count

            return [
                key
                for key in ordered
                if self._key_retry_after.get(key, 0) <= now
            ]

    def _cool_down_key(self, key: str) -> None:
        with self._key_lock:
            self._key_retry_after[key] = (
                time.monotonic() + KEY_COOLDOWN_SECONDS
            )

    # ---------------------------------
    # Gemini API
    # ---------------------------------

    def _call_llm(self, question: str, context: str) -> str | None:
        keys = self._keys_to_try()

        if not keys:
            logger.warning(
                "Gemini unavailable: no configured keys or all keys "
                "are temporarily rate-limited"
            )
            return None

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

        payload = {
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"EVENTS:\n{context}\n\n"
                                f"QUESTION: {question}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 256,
            },
        }

        body_bytes = json.dumps(payload).encode("utf-8")

        for key in keys:
            request = urllib.request.Request(
                url,
                data=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": key,
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))

                candidates = body.get("candidates", [])
                if not candidates:
                    logger.warning("Gemini returned no answer candidates")
                    return None

                parts = candidates[0].get("content", {}).get("parts", [])
                text_parts = [
                    part["text"].strip()
                    for part in parts
                    if isinstance(part.get("text"), str)
                    and part["text"].strip()
                ]

                answer = "\n".join(text_parts).strip()
                if answer:
                    return answer

                logger.warning("Gemini returned an empty answer")
                return None

            except urllib.error.HTTPError as error:
                # Read the error response to distinguish quota errors
                # from invalid requests or credentials.
                try:
                    error_body = error.read().decode(
                        "utf-8", errors="replace"
                    )
                except OSError:
                    error_body = ""

                error_text = error_body.lower()
                quota_error = (
                    error.code == 429
                    or (
                        error.code == 403
                        and any(
                            marker in error_text
                            for marker in (
                                "resource_exhausted",
                                "quota",
                                "rate limit",
                                "ratelimit",
                            )
                        )
                    )
                )

                if quota_error:
                    self._cool_down_key(key)
                    logger.warning(
                        "Gemini key was rate-limited; trying another "
                        "eligible key if available"
                    )
                    continue

                # Invalid credentials or requests should not cause
                # repeated attempts against every configured key.
                logger.warning(
                    "Gemini API returned HTTP %s; using fallback",
                    error.code,
                )
                return None

            except (
                urllib.error.URLError,
                OSError,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
            ) as error:
                logger.warning(
                    "Gemini request failed (%s)",
                    type(error).__name__,
                )
                return None

        logger.warning(
            "No eligible Gemini key succeeded; using event summary"
        )
        return None
