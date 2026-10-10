import unittest
from datetime import datetime, time, timedelta, timezone

from spory.estimator import ChargeEstimator
from spory.gui.model import build_snapshot, service_state
from spory.hardware import BatteryStatus
from spory.schedule import Schedule, WeeklyRule, parse_weekdays
from spory.state import Config

UTC = timezone.utc
NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)  # Friday


def config(**kw):
    schedule = Schedule(weekly=[WeeklyRule(parse_weekdays("daily"), time(9, 30))], tz=UTC)
    return Config(normal_cap=60, schedule=schedule, estimator=ChargeEstimator([1.0] * 10), **kw)


class ServiceStateTests(unittest.TestCase):
    def test_missing_and_stale(self):
        self.assertFalse(service_state(None, NOW).running)
        stale = {"updated_at": (NOW - timedelta(minutes=10)).isoformat(), "writable": True}
        self.assertEqual(service_state(stale, NOW).tone, "bad")

    def test_running_backends(self):
        base = {"updated_at": NOW.isoformat(), "backend": "msi", "reason": "x"}
        self.assertEqual(service_state({**base, "writable": True}, NOW).label, "msi")
        self.assertEqual(service_state({**base, "writable": False}, NOW).tone, "warn")
        self.assertIn("dry run", service_state({**base, "writable": True, "dry_run": True}, NOW).label)


class SnapshotTests(unittest.TestCase):
    def test_holding_shows_start_time(self):
        snap = build_snapshot(config(), BatteryStatus(60, True, False), NOW, [], None)
        self.assertEqual(snap.state, "HOLDING")
        self.assertIn(("next", "09:30 → 100%"), snap.rows)
        self.assertIn(("start", "08:35"), snap.rows)  # 09:30 - 40 min charge - 15 min margin
        self.assertFalse(snap.charging_now)
        self.assertEqual(snap.runway.deadline, datetime(2026, 10, 2, 9, 30, tzinfo=UTC))
        self.assertEqual(snap.runway.window_start, datetime(2026, 10, 2, 8, 35, tzinfo=UTC))
        reached = [pct for at, pct, _ in snap.runway.future if at <= snap.runway.deadline]
        self.assertGreaterEqual(reached[-1], 99.5)

    def test_charging_for_departure(self):
        now = NOW.replace(hour=9)
        snap = build_snapshot(config(), BatteryStatus(80, True, True), now, [], None)
        self.assertEqual(snap.state, "CHARGING")
        self.assertIn(("full", "09:20"), snap.rows)
        self.assertTrue(snap.charging_now)
        self.assertEqual(snap.runway.window_start, now)

    def test_late_charge_is_flagged(self):
        now = NOW.replace(hour=9, minute=15)
        snap = build_snapshot(config(), BatteryStatus(60, True, True), now, [], None)
        self.assertEqual(snap.tone, "bad")
        self.assertIn(("full", "09:55 late"), snap.rows)

    def test_charge_now_override(self):
        cfg = config(charge_now_until=NOW + timedelta(hours=2))
        snap = build_snapshot(cfg, BatteryStatus(60, True, True), NOW, [], None)
        self.assertEqual(snap.state, "CHARGING")
        self.assertIn(("override", "until 08:00"), snap.rows)

    def test_no_departures(self):
        cfg = config()
        cfg.schedule.weekly = []
        snap = build_snapshot(cfg, BatteryStatus(55, False, False), NOW, [], None)
        self.assertEqual(snap.rows, [("next", "—")])

    def test_above_limit(self):
        cfg = config()
        cfg.schedule.weekly = []
        snap = build_snapshot(cfg, BatteryStatus(100, True, False), NOW, [], None)
        self.assertEqual(snap.state, "ABOVE LIMIT")
        self.assertIn(("drain", "unplug to reach 60%"), snap.rows)
        unplugged = build_snapshot(cfg, BatteryStatus(90, False, False), NOW, [], None)
        self.assertNotIn("drain", [k for k, _ in unplugged.rows])

    def test_past_is_limited_to_recent_hours(self):
        history = [(NOW - timedelta(hours=h), 70.0) for h in (12, 2, 1)]
        snap = build_snapshot(config(), BatteryStatus(60, True, False), NOW, history, None)
        self.assertEqual(len(snap.runway.past), 2)

    def test_projection_stops_at_departure(self):
        snap = build_snapshot(config(), BatteryStatus(60, True, False), NOW, [], None)
        self.assertLessEqual(snap.runway.future[-1][0], snap.runway.deadline)
        self.assertNotIn("limit", [k for k, _ in snap.rows])


if __name__ == "__main__":
    unittest.main()
