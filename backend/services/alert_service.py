"""Alerts and ESP32 hardware actions.

When ESP32_URL is set, an alert is an HTTP GET to the ESP32:

    GET {ESP32_URL}/alert?type=<EVENT_TYPE>&duration=<seconds>

which the firmware in firmware/esp32_cam/ maps to the LED and buzzer.
With no ESP32_URL the service runs in dry-run mode and only logs.
"""

import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AlertResult:
    sent: bool
    dry_run: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "sent": self.sent,
            "dry_run": self.dry_run,
            "reason": self.reason,
        }


class AlertService:

    def __init__(
        self,
        esp32_url: str = "",
        event_types: list[str] | None = None,
        cooldown_sec: float = 30.0,
        duration_sec: int = 3,
        clock=time.monotonic,
    ):
        self.esp32_url = esp32_url.rstrip("/")
        self.event_types = set(
            event_types
            if event_types is not None
            else ["UNATTENDED_OBJECT", "LOITERING"]
        )
        self.cooldown_sec = cooldown_sec
        self.duration_sec = duration_sec
        self._clock = clock
        self._last_sent: dict[str, float] = {}

    @property
    def dry_run(self) -> bool:
        return not self.esp32_url

    def handle(
        self,
        event_type: str,
        verification: str | None = None,
    ) -> AlertResult:
        """Decide whether an event should raise an alert, and raise it.

        verification is the VLM verdict (YES / NO / UNKNOWN / None).
        Only an explicit NO (the VLM contradicts the engine) suppresses
        the alert; the deterministic engine stays the primary signal.
        """

        if event_type not in self.event_types:
            return AlertResult(False, self.dry_run, "event type not alertable")

        if verification == "NO":
            return AlertResult(
                False,
                self.dry_run,
                "suppressed: visual check contradicted the event",
            )

        now = self._clock()
        last = self._last_sent.get(event_type)

        if last is not None and now - last < self.cooldown_sec:
            return AlertResult(False, self.dry_run, "cooldown active")

        self._last_sent[event_type] = now

        if self.dry_run:
            logger.info("ALERT (dry run): %s", event_type)
            return AlertResult(True, True, "dry run: logged only")

        return self._send(event_type)

    def _send(self, event_type: str) -> AlertResult:

        query = urllib.parse.urlencode(
            {"type": event_type, "duration": self.duration_sec}
        )

        url = f"{self.esp32_url}/alert?{query}"

        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                ok = 200 <= response.status < 300

            return AlertResult(ok, False, f"ESP32 responded {response.status}")

        except (urllib.error.URLError, OSError) as error:
            logger.warning("ESP32 alert failed: %s", error)
            # Allow an immediate retry on the next event.
            self._last_sent.pop(event_type, None)
            return AlertResult(False, False, f"ESP32 unreachable: {error}")
