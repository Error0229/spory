"""Hardware-independent deadline planner."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True)
class ChargePlan:
    start_at: datetime
    estimated_finish: datetime
    start_now: bool
    likely_late: bool
    already_ready: bool


def plan_charge(
    *,
    now: datetime,
    deadline: datetime,
    current_percent: float,
    target_percent: float,
    estimated_minutes: float,
    safety_margin_minutes: float = 15,
) -> ChargePlan:
    """Compute when to raise the charge cap; never writes to hardware."""
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError("now and deadline must be timezone-aware")
    if deadline <= now:
        raise ValueError("deadline must be in the future")
    for value in (current_percent, target_percent):
        if not isfinite(value) or not 0 <= value <= 100:
            raise ValueError("percentages must be finite and between 0 and 100")
    for value in (estimated_minutes, safety_margin_minutes):
        if not isfinite(value) or value < 0:
            raise ValueError("durations must be finite and nonnegative")
    if target_percent < current_percent:
        raise ValueError("target cannot be below current charge")

    ready = current_percent >= target_percent
    duration = timedelta(minutes=0 if ready else estimated_minutes)
    ideal_start = deadline - duration - timedelta(minutes=safety_margin_minutes)
    start = max(now, ideal_start)
    finish = start + duration
    return ChargePlan(start, finish, not ready and start == now, finish > deadline, ready)
