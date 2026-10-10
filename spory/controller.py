"""Decide which charge cap should apply right now."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from spory.hardware import BatteryStatus
from spory.planner import ChargePlan, plan_charge
from spory.schedule import Deadline
from spory.state import ActiveWindow, Config


@dataclass(frozen=True)
class Decision:
    cap: float
    reason: str
    deadline: Deadline | None
    plan: ChargePlan | None
    active: ActiveWindow | None


def decide(config: Config, status: BatteryStatus, now: datetime) -> Decision:
    """Pure decision: no I/O, so it is shared by `run`, `status` and the simulator."""
    normal = config.normal_cap
    if config.charge_now_until and now < config.charge_now_until:
        return Decision(
            100, f"charge-now override until {config.charge_now_until:%a %H:%M}", None, None, None
        )

    deadline = config.schedule.next_deadline(now)
    if deadline is None:
        return Decision(normal, "no upcoming deadline", None, None, None)
    target = max(deadline.target_percent, normal)

    active = config.active
    if active and active.deadline == deadline.at and active.deadline > now:
        return Decision(
            target, f"charging for {deadline.at:%a %H:%M} deadline", deadline, None, active
        )

    plan = plan_charge(
        now=now,
        deadline=deadline.at,
        current_percent=min(status.percent, target),
        target_percent=target,
        estimated_minutes=config.estimator.estimate_minutes(min(status.percent, target), target),
        safety_margin_minutes=config.safety_margin_minutes,
    )
    if plan.start_at <= now:
        reason = f"charging for {deadline.at:%a %H:%M} deadline"
        if plan.likely_late:
            reason += " (may finish late)"
        return Decision(target, reason, deadline, plan, ActiveWindow(deadline.at, target))
    return Decision(
        normal, f"holding at {normal:g}%; charging starts {plan.start_at:%a %H:%M}", deadline, plan, None
    )
