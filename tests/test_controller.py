import unittest
from datetime import datetime, time, timedelta, timezone

from spory.controller import decide
from spory.estimator import ChargeEstimator
from spory.hardware import BatteryStatus
from spory.schedule import Schedule, WeeklyRule, parse_weekdays
from spory.state import ActiveWindow, Config

UTC = timezone.utc
DEADLINE = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
PLUGGED_60 = BatteryStatus(60, True, False)


def config(**kw):
    schedule = Schedule(weekly=[WeeklyRule(parse_weekdays("daily"), time(9, 30))], tz=UTC)
    # 1 minute per percent: 60% -> 100% takes 40 minutes.
    return Config(
        normal_cap=60,
        safety_margin_minutes=20,
        schedule=schedule,
        estimator=ChargeEstimator([1.0] * 10),
        **kw,
    )


class ControllerTests(unittest.TestCase):
    def test_holds_normal_cap_before_start(self):
        d = decide(config(), PLUGGED_60, DEADLINE - timedelta(hours=2))
        self.assertEqual(d.cap, 60)
        self.assertEqual(d.plan.start_at, DEADLINE - timedelta(minutes=60))
        self.assertIsNone(d.active)

    def test_raises_cap_at_start(self):
        d = decide(config(), PLUGGED_60, DEADLINE - timedelta(minutes=60))
        self.assertEqual(d.cap, 100)
        self.assertEqual(d.active, ActiveWindow(DEADLINE, 100))

    def test_active_window_does_not_flap(self):
        # At 80% a fresh plan would start later, but the open window is kept.
        cfg = config(active=ActiveWindow(DEADLINE, 100))
        d = decide(cfg, BatteryStatus(80, True, True), DEADLINE - timedelta(minutes=50))
        self.assertEqual(d.cap, 100)

    def test_back_to_normal_after_deadline(self):
        cfg = config(active=ActiveWindow(DEADLINE, 100))
        d = decide(cfg, BatteryStatus(100, True, False), DEADLINE + timedelta(minutes=1))
        self.assertEqual(d.cap, 60)
        self.assertIsNone(d.active)

    def test_late_start_warns(self):
        d = decide(config(), PLUGGED_60, DEADLINE - timedelta(minutes=10))
        self.assertEqual(d.cap, 100)
        self.assertIn("late", d.reason)

    def test_charge_now_override(self):
        now = DEADLINE - timedelta(hours=5)
        d = decide(config(charge_now_until=now + timedelta(hours=1)), PLUGGED_60, now)
        self.assertEqual(d.cap, 100)
        d = decide(config(charge_now_until=now - timedelta(hours=1)), PLUGGED_60, now)
        self.assertEqual(d.cap, 60)

    def test_target_below_normal_cap_keeps_normal(self):
        cfg = config()
        cfg.schedule.weekly = [WeeklyRule(parse_weekdays("daily"), time(9, 30), 50)]
        d = decide(cfg, PLUGGED_60, DEADLINE - timedelta(minutes=5))
        self.assertEqual(d.cap, 60)

    def test_no_deadline(self):
        cfg = config()
        cfg.schedule.weekly = []
        self.assertEqual(decide(cfg, PLUGGED_60, DEADLINE).cap, 60)


if __name__ == "__main__":
    unittest.main()
