"""Charge-time estimation that accounts for slowdown near full."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from math import isfinite
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from spory.history import BatterySample

BAND_WIDTH = 10
BANDS = 100 // BAND_WIDTH

# Minutes per percent for each 10% band. Lithium cells switch to
# constant-voltage charging near full, so the last bands are slower.
DEFAULT_MINUTES_PER_PERCENT = (0.9,) * 8 + (1.4, 2.5)

# How many percent points of observed charging the default curve is worth.
# Learned rates replace the defaults gradually as history accumulates.
PRIOR_WEIGHT_PERCENT = 5.0

# Samples further apart than this are treated as separate sessions
# (for example across sleep), so the gap is not counted as charge time.
MAX_SAMPLE_GAP = timedelta(minutes=15)


def _band(percent: float) -> int:
    return min(int(percent // BAND_WIDTH), BANDS - 1)


def _check_percent(value: float) -> None:
    if not isfinite(value) or not 0 <= value <= 100:
        raise ValueError("percentages must be finite and between 0 and 100")


@dataclass
class ChargeEstimator:
    minutes_per_percent: list[float] = field(
        default_factory=lambda: list(DEFAULT_MINUTES_PER_PERCENT)
    )

    def __post_init__(self) -> None:
        if len(self.minutes_per_percent) != BANDS:
            raise ValueError(f"expected {BANDS} bands")
        if any(not isfinite(r) or r <= 0 for r in self.minutes_per_percent):
            raise ValueError("rates must be finite and positive")

    def rate_at(self, percent: float) -> float:
        """Minutes needed to gain one percent at the given charge level."""
        return self.minutes_per_percent[_band(percent)]

    def estimate_minutes(self, current_percent: float, target_percent: float) -> float:
        """Minutes to charge from current to target while plugged in."""
        _check_percent(current_percent)
        _check_percent(target_percent)
        total = 0.0
        percent = current_percent
        while percent < target_percent:
            band = _band(percent)
            band_end = min((band + 1) * BAND_WIDTH, target_percent)
            total += (band_end - percent) * self.minutes_per_percent[band]
            percent = band_end
        return total

    @classmethod
    def fit(
        cls, samples: Iterable[BatterySample], prior: ChargeEstimator | None = None
    ) -> ChargeEstimator:
        """Blend observed charging speed per band into the prior curve.

        Only consecutive samples that are both plugged in and charging count,
        so time spent holding at a cap does not look like slow charging.
        """
        prior = prior or cls()
        minutes = [0.0] * BANDS
        gained = [0.0] * BANDS
        ordered = sorted(samples, key=lambda s: s.at)
        for a, b in zip(ordered, ordered[1:]):
            gap = b.at - a.at
            if not (timedelta(0) < gap <= MAX_SAMPLE_GAP):
                continue
            if not (a.plugged_in and a.charging and b.plugged_in and b.charging):
                continue
            delta = b.percent - a.percent
            if delta < 0:
                continue
            band = _band(a.percent)
            minutes[band] += gap.total_seconds() / 60
            gained[band] += delta
        rates = [
            (prior_rate * PRIOR_WEIGHT_PERCENT + minutes[i])
            / (PRIOR_WEIGHT_PERCENT + gained[i])
            if gained[i] > 0
            else prior_rate
            for i, prior_rate in enumerate(prior.minutes_per_percent)
        ]
        return cls(rates)
