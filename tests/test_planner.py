import unittest
from datetime import datetime, timedelta, timezone

from spory.planner import plan_charge


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc)
        self.deadline = self.now + timedelta(hours=2, minutes=30)

    def test_schedules_with_margin(self):
        result = plan_charge(
            now=self.now, deadline=self.deadline, current_percent=60,
            target_percent=100, estimated_minutes=70, safety_margin_minutes=20,
        )
        self.assertEqual(result.start_at, self.deadline - timedelta(minutes=90))
        self.assertEqual(result.estimated_finish, self.deadline - timedelta(minutes=20))
        self.assertFalse(result.start_now)
        self.assertFalse(result.likely_late)

    def test_starts_now_and_warns_when_time_is_insufficient(self):
        result = plan_charge(
            now=self.now, deadline=self.now + timedelta(minutes=50),
            current_percent=60, target_percent=100, estimated_minutes=70,
        )
        self.assertTrue(result.start_now)
        self.assertTrue(result.likely_late)

    def test_already_ready(self):
        result = plan_charge(
            now=self.now, deadline=self.deadline, current_percent=100,
            target_percent=100, estimated_minutes=70,
        )
        self.assertTrue(result.already_ready)
        self.assertFalse(result.start_now)

    def test_invalid_percentage(self):
        with self.assertRaises(ValueError):
            plan_charge(
                now=self.now, deadline=self.deadline, current_percent=101,
                target_percent=100, estimated_minutes=20,
            )


if __name__ == "__main__":
    unittest.main()
