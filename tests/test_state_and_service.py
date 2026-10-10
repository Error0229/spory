import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from spory.estimator import ChargeEstimator
from spory.hardware import BatteryStatus, SimulatedBattery
from spory.history import HistoryLog
from spory.reminders import ReminderOnlyBattery
from spory.schedule import OneTimeDeadline, WeeklyRule, parse_weekdays
from spory.service import Service
from spory.state import ActiveWindow, Config, Store

UTC = timezone.utc


class StoreTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            cfg = Config(normal_cap=55, safety_margin_minutes=10)
            cfg.schedule.weekly.append(WeeklyRule(parse_weekdays("mon-fri"), time(9, 30), 95))
            at = datetime(2026, 10, 9, 7, 0, tzinfo=UTC)
            cfg.schedule.one_time.append(OneTimeDeadline(at, 100))
            cfg.schedule.skip_dates.add(date(2026, 10, 12))
            cfg.charge_now_until = at
            cfg.active = ActiveWindow(at, 100)
            cfg.original_limit = 100.0
            cfg.notice_seen = True
            store.save(cfg)
            loaded = store.load()
            self.assertEqual(loaded.to_dict(), cfg.to_dict())
            self.assertEqual(loaded.schedule.weekly, cfg.schedule.weekly)

    def test_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Store(Path(tmp)).load().normal_cap, 60)

    def test_history_skips_torn_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            path.write_text('{"at": "2026-10-02T08:00:00+00:00", "percent": 60, '
                            '"plugged_in": true, "charging": false}\n{"at": "2026', encoding="utf-8")
            self.assertEqual(len(HistoryLog(path).read()), 1)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.now = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
        cfg = Config()
        cfg.schedule.one_time.append(OneTimeDeadline(self.now + timedelta(minutes=30)))
        self.store.save(cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_only_backend_sends_reminder_once(self):
        sent = []
        adapter = ReminderOnlyBattery(lambda: BatteryStatus(60, False, False))
        service = Service(self.store, adapter, clock=lambda: self.now, notify=sent.append)
        result = service.tick()
        self.assertEqual(result.decision.cap, 100)
        self.assertFalse(result.applied)
        service.tick()
        self.assertEqual(len(sent), 1)
        self.assertIn("Plug in", sent[0])
        self.assertEqual(len(HistoryLog(self.store.history_path).read()), 2)
        self.assertIsNotNone(self.store.load().active)

    def test_writable_backend_applies_and_corrects_drift(self):
        battery = SimulatedBattery(ChargeEstimator(), percent=60, cap=60)
        service = Service(self.store, battery, clock=lambda: self.now)
        self.assertTrue(service.tick().applied)
        self.assertEqual(battery.cap, 100)
        self.assertFalse(service.tick().applied)
        battery.cap = 80  # changed behind spory's back, e.g. by the vendor app
        self.assertTrue(service.tick().applied)
        self.assertEqual(battery.cap, 100)

    def test_dry_run_never_writes(self):
        battery = SimulatedBattery(ChargeEstimator(), percent=60, cap=60)
        service = Service(self.store, battery, dry_run=True, clock=lambda: self.now)
        self.assertIn("dry run", service.tick().message)
        self.assertEqual(service.tick().message, "")
        service.close()
        self.assertEqual(battery.cap, 60)

    def test_close_restores_normal_cap(self):
        battery = SimulatedBattery(ChargeEstimator(), percent=60, cap=60)
        service = Service(self.store, battery, clock=lambda: self.now)
        service.tick()
        service.close()
        self.assertEqual(battery.cap, 60)


if __name__ == "__main__":
    unittest.main()
