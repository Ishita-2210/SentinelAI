import os
import tempfile
import unittest
from datetime import timedelta

from backend.database.event_database import EventDatabase
from backend.retrieval.retriever import EventRetriever, plan_query
from tests.helpers import NOW, add_event


class PlanQueryTests(unittest.TestCase):

    def test_event_type_and_window(self):
        plan = plan_query("Was there an unattended bag in the last 30 minutes?", NOW)
        self.assertEqual(plan.event_types, ["UNATTENDED_OBJECT"])
        self.assertEqual(plan.since, NOW - timedelta(minutes=30))
        self.assertIsNone(plan.until)

    def test_entered(self):
        plan = plan_query("Who entered the zone?", NOW)
        self.assertEqual(plan.event_types, ["PERSON_ENTERED"])

    def test_left_behind_is_unattended_not_exit(self):
        plan = plan_query("anything left behind?", NOW)
        self.assertEqual(plan.event_types, ["UNATTENDED_OBJECT"])

    def test_yesterday_window(self):
        plan = plan_query("what happened yesterday", NOW)
        self.assertEqual(plan.since.day, 16)
        self.assertEqual(plan.until.day, 17)
        self.assertEqual((plan.since.hour, plan.since.minute), (0, 0))

    def test_today_window(self):
        plan = plan_query("anything today?", NOW)
        self.assertEqual(plan.since, NOW.replace(hour=0, minute=0))

    def test_hours_and_days(self):
        self.assertEqual(
            plan_query("last 2 hours", NOW).since, NOW - timedelta(hours=2)
        )
        self.assertEqual(
            plan_query("past 3 days", NOW).since, NOW - timedelta(days=3)
        )

    def test_generic_question_has_no_keywords(self):
        plan = plan_query("What happened recently?", NOW)
        self.assertEqual(plan.keywords, [])
        self.assertEqual(plan.event_types, [])


class SearchTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = EventDatabase(os.path.join(self.tmp.name, "e.db"))
        self.retriever = EventRetriever(self.database)

        self.bag_recent = add_event(
            self.database, "UNATTENDED_OBJECT", "backpack", minutes_ago=10,
            description="backpack unattended for 40s",
        )
        self.bag_old = add_event(
            self.database, "UNATTENDED_OBJECT", "backpack", minutes_ago=600,
            description="backpack unattended for 40s",
        )
        self.loiter = add_event(
            self.database, "LOITERING", "person", minutes_ago=20, zone="lobby",
            description="person lingering for 70s",
        )
        self.bottle = add_event(
            self.database, "ZONE_CHANGED", "bottle", minutes_ago=30,
            description="bottle moved to shelf",
        )

    def tearDown(self):
        self.database.close()
        self.tmp.cleanup()

    def ids(self, question, **kwargs):
        return [e["id"] for e in self.retriever.search(question, now=NOW, **kwargs)]

    def test_type_and_window_filter(self):
        self.assertEqual(
            self.ids("unattended object in the last hour"),
            [self.bag_recent],
        )

    def test_type_without_window_returns_all_of_type_newest_first(self):
        self.assertEqual(
            self.ids("any unattended objects?"),
            [self.bag_old, self.bag_recent],
        )

    def test_generic_question_returns_recent_events(self):
        self.assertEqual(len(self.ids("what happened recently?")), 4)

    def test_keyword_search_uses_fts(self):
        self.assertEqual(self.ids("tell me about the bottle"), [self.bottle])
        self.assertEqual(self.retriever.last_search_mode, "fts")

    def test_unmatched_topic_returns_nothing(self):
        self.assertEqual(self.ids("tell me about dinosaurs"), [])

    def test_unmatched_topic_with_window_falls_back_to_window(self):
        # No text hit but a time window was asked for: show that window.
        ids = self.ids("anything about dinosaurs in the last hour")
        self.assertEqual(set(ids), {self.bag_recent, self.loiter, self.bottle})

    def test_special_characters_do_not_break_search(self):
        self.assertEqual(self.ids('"; DROP TABLE events; -- bottle'), [self.bottle])
        self.assertEqual(self.database.count_events(), 4)

    def test_limit(self):
        self.assertEqual(len(self.ids("what happened recently?", limit=2)), 2)

    def test_format_context_marks_unverified(self):
        self.database.update_verification(self.bag_recent, "NO", "bag is held by a person")
        events = self.retriever.search("unattended object in the last hour", now=NOW)
        text = EventRetriever.format_context(events)

        self.assertIn(f"[event {self.bag_recent}]", text)
        self.assertIn("visual check: NO", text)
        self.assertIn("bag is held by a person", text)

        other = EventRetriever.format_context(
            self.retriever.search("lingering", now=NOW)
        )
        self.assertIn("NOT_VERIFIED", other)


if __name__ == "__main__":
    unittest.main()
