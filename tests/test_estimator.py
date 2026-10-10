import unittest
from datetime import datetime, timedelta, timezone

from spory.estimator import ChargeEstimator
from spory.history import BatterySample


def charging_run(start, percents, minutes_apart, plugged=True, charging=True):
    return [
        BatterySample(start + timedelta(minutes=i * minutes_apart), p, plugged, charging)
        for i, p in enumerate(percents)
    ]


class EstimatorTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)

    def test_slower_near_full(self):
        est = ChargeEstimator()
        self.assertGreater(est.estimate_minutes(90, 100), est.estimate_minutes(50, 60))

    def test_estimate_crosses_bands(self):
        est = ChargeEstimator([1.0] * 9 + [3.0])
        self.assertAlmostEqual(est.estimate_minutes(85, 100), 5 * 1.0 + 10 * 3.0)
        self.assertEqual(est.estimate_minutes(70, 70), 0)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            ChargeEstimator([1.0] * 3)
        with self.assertRaises(ValueError):
            ChargeEstimator().estimate_minutes(-1, 50)

    def test_fit_moves_toward_observed_rate(self):
        # 60% -> 70% in 40 minutes: 4 min/percent, far slower than the default.
        samples = charging_run(self.start, range(60, 71), 4)
        fitted = ChargeEstimator.fit(samples)
        prior = ChargeEstimator().minutes_per_percent[6]
        self.assertGreater(fitted.minutes_per_percent[6], prior)
        self.assertLess(fitted.minutes_per_percent[6], 4.0)
        self.assertEqual(fitted.minutes_per_percent[0], ChargeEstimator().minutes_per_percent[0])

    def test_fit_ignores_holding_and_gaps(self):
        holding = charging_run(self.start, [60] * 30, 1, charging=False)
        gap = [
            BatterySample(self.start, 60, True, True),
            BatterySample(self.start + timedelta(hours=8), 61, True, True),
        ]
        self.assertEqual(ChargeEstimator.fit(holding + gap), ChargeEstimator())


if __name__ == "__main__":
    unittest.main()
