import unittest

from backend.services.alert_service import AlertService
from tests.helpers import FakeServer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class AlertTests(unittest.TestCase):

    def test_non_alertable_type(self):
        result = AlertService().handle("PERSON_ENTERED")
        self.assertFalse(result.sent)
        self.assertEqual(result.reason, "event type not alertable")

    def test_dry_run_without_esp32(self):
        service = AlertService(esp32_url="")
        self.assertTrue(service.dry_run)

        result = service.handle("UNATTENDED_OBJECT", "YES")
        self.assertTrue(result.sent)
        self.assertTrue(result.dry_run)

    def test_visual_no_suppresses_but_unknown_does_not(self):
        service = AlertService(cooldown_sec=0)

        self.assertFalse(service.handle("LOITERING", "NO").sent)
        self.assertTrue(service.handle("LOITERING", "UNKNOWN").sent)
        self.assertTrue(service.handle("LOITERING", None).sent)

    def test_cooldown(self):
        clock = Clock()
        service = AlertService(cooldown_sec=30, clock=clock)

        self.assertTrue(service.handle("UNATTENDED_OBJECT").sent)

        clock.now += 10
        blocked = service.handle("UNATTENDED_OBJECT")
        self.assertFalse(blocked.sent)
        self.assertEqual(blocked.reason, "cooldown active")

        # Cooldown is per event type.
        self.assertTrue(service.handle("LOITERING").sent)

        clock.now += 25
        self.assertTrue(service.handle("UNATTENDED_OBJECT").sent)

    def test_sends_request_to_esp32(self):
        with FakeServer({"ok": True}) as server:
            service = AlertService(esp32_url=server.url + "/", duration_sec=5)
            result = service.handle("UNATTENDED_OBJECT", "YES")

        self.assertTrue(result.sent)
        self.assertFalse(result.dry_run)
        self.assertEqual(
            server.requests[0]["path"],
            "/alert?type=UNATTENDED_OBJECT&duration=5",
        )

    def test_unreachable_esp32_allows_immediate_retry(self):
        service = AlertService(esp32_url="http://127.0.0.1:1", cooldown_sec=300)

        first = service.handle("UNATTENDED_OBJECT")
        self.assertFalse(first.sent)
        self.assertIn("unreachable", first.reason)

        # Failed delivery must not start the cooldown.
        second = service.handle("UNATTENDED_OBJECT")
        self.assertNotEqual(second.reason, "cooldown active")

    def test_esp32_http_error_is_not_reported_as_sent(self):
        with FakeServer({}, status=500) as server:
            result = AlertService(esp32_url=server.url).handle("LOITERING")

        self.assertFalse(result.sent)


if __name__ == "__main__":
    unittest.main()
