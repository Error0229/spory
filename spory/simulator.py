"""Replay the controller against a simulated battery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from spory.controller import Decision, decide
from spory.hardware import BatteryStatus, SimulatedBattery
from spory.state import Config


@dataclass(frozen=True)
class Step:
    at: datetime
    status: BatteryStatus
    decision: Decision


@dataclass(frozen=True)
class DeadlineResult:
    deadline: datetime
    target_percent: float
    percent: float

    @property
    def met(self) -> bool:
        return self.percent >= self.target_percent - 0.5


@dataclass(frozen=True)
class Simulation:
    steps: list[Step]
    deadlines: list[DeadlineResult]


def simulate(
    config: Config,
    start: datetime,
    hours: float = 48,
    start_percent: float = 60,
    step_minutes: float = 5,
    away_hours: float = 9,
) -> Simulation:
    """Run from `start`, unplugging at each deadline for `away_hours`."""
    config = replace(config, active=None)
    end = start + timedelta(hours=hours)
    away = timedelta(hours=away_hours)
    all_deadlines = config.schedule.upcoming(start - away, days=int(hours // 24) + 3)
    battery = SimulatedBattery(config.estimator, percent=start_percent, cap=config.normal_cap)
    step = timedelta(minutes=step_minutes)

    steps: list[Step] = []
    results: list[DeadlineResult] = []
    pending = [d for d in all_deadlines if start < d.at <= end]
    now = start
    while now < end:
        while pending and pending[0].at <= now:
            d = pending.pop(0)
            results.append(DeadlineResult(d.at, d.target_percent, round(battery.percent, 1)))
        battery.plugged_in = not any(d.at <= now < d.at + away for d in all_deadlines)
        status = battery.read_status()
        decision = decide(config, status, now)
        config.active = decision.active
        battery.set_charge_cap(decision.cap)
        steps.append(Step(now, status, decision))
        battery.advance(step_minutes)
        now += step
    return Simulation(steps, results)
