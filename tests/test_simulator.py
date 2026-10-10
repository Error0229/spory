import unittest
from datetime import datetime, time, timezone

from spory.estimator import ChargeEstimator
from spory.hardware import SimulatedBattery
from spory.schedule import Schedule, WeeklyRule, parse_weekdays
from spory.simulator import simulate
from spory.state import Config

UTC = timezone.utc


class SimulatedBatteryTests(unittest.TestCase):
    def test_charges_to_cap_and_never_discharges_on_ac(self):
        b = SimulatedBattery(ChargeEstimator([1.0] * 10), percent=60, cap=100)
        b.advance(30)
        self.assertAlmostEqual(b.percent, 90)
        b.set_charge_cap(60)
        b.advance(60)
        self.assertAlmostEqual(b.percent, 90)

    def test_drains_unplugged(self):
        b = SimulatedBattery(
            ChargeEstimator(), percent=80, plugged_in=False, drain_percent_per_hour=10
        )
        b.advance(60)
        self.assertAlmostEqual(b.percent, 70)


class SimulationTests(unittest.TestCase):
    def test_weekday_deadlines_are_met_and_cap_restored(self):
        schedule = Schedule(weekly=[WeeklyRule(parse_weekdays("mon-fri"), time(9, 30))], tz=UTC)
        cfg = Config(normal_cap=60, schedule=schedule)
        start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)  # Monday
        result = simulate(cfg, start, hours=72, start_percent=60)
        self.assertEqual(len(result.deadlines), 3)
        self.assertTrue(all(d.met for d in result.deadlines), result.deadlines)
        # Overnight before a deadline, the cap is back at normal.
        night = [s for s in result.steps if s.at.hour == 3]
        self.assertTrue(all(s.decision.cap == 60 for s in night))
        # Charging starts close to the deadline, not hours early.
        first_full = next(s for s in result.steps if s.decision.cap == 100)
        self.assertGreaterEqual(first_full.at, datetime(2026, 10, 5, 8, 0, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
