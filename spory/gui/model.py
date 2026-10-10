"""What the window shows, computed without Qt so it can be tested."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from spory.controller import Decision, decide
from spory.hardware import BatteryStatus
from spory.simulator import simulate
from spory.state import Config

SERVICE_STALE_AFTER = timedelta(minutes=3)
PAST_HOURS = 3
NO_DEADLINE_HOURS = 6


@dataclass
class Runway:
    now: datetime
    percent: float
    normal_cap: float
    past: list[tuple[datetime, float]] = field(default_factory=list)
    # (time, projected percent, inside a charge window)
    future: list[tuple[datetime, float, bool]] = field(default_factory=list)
    deadline: datetime | None = None
    deadline_target: float | None = None
    window_start: datetime | None = None


@dataclass(frozen=True)
class ServiceState:
    running: bool
    label: str
    tone: str  # "good", "warn" or "bad"
    detail: str


@dataclass
class Snapshot:
    status: BatteryStatus
    decision: Decision
    state: str  # HOLDING, CHARGING, READY or ABOVE LIMIT; shown with the current limit
    tone: str  # "good", "warn", "bad" or "muted"
    rows: list[tuple[str, str]]  # short key/value lines
    charging_now: bool
    runway: Runway
    service: ServiceState


def service_state(published: dict | None, now: datetime) -> ServiceState:
    if not published:
        return ServiceState(False, "service off", "bad", "not installed or not running")
    try:
        updated = datetime.fromisoformat(published["updated_at"])
    except (KeyError, ValueError):
        return ServiceState(False, "service off", "bad", "status file unreadable")
    if now - updated > SERVICE_STALE_AFTER:
        return ServiceState(False, "service off", "bad", f"last check {updated:%a %H:%M}")
    backend = str(published.get("backend", "?"))
    detail = f"checked {updated:%H:%M}"
    if not published.get("writable"):
        return ServiceState(True, "reminders", "warn", detail)
    if published.get("dry_run"):
        return ServiceState(True, f"{backend} · dry run", "warn", detail)
    return ServiceState(True, backend, "good", detail)


def _when(at: datetime, now: datetime) -> str:
    at = at.astimezone(now.tzinfo)
    return f"{at:%H:%M}" if at.date() == now.date() else f"{at:%a %H:%M}".lower()


def summarize(
    config: Config, status: BatteryStatus, decision: Decision, now: datetime
) -> tuple[str, str, list[tuple[str, str]]]:
    normal = config.normal_cap
    deadline = decision.deadline
    rows: list[tuple[str, str]] = []  # the limit itself is shown next to the state

    if config.charge_now_until and now < config.charge_now_until:
        rows.append(("override", f"until {_when(config.charge_now_until, now)}"))
    elif deadline:
        rows.append(("next", f"{_when(deadline.at, now)} → {max(deadline.target_percent, normal):g}%"))
    else:
        rows.append(("next", "—"))

    if decision.cap > normal:
        if status.percent >= decision.cap:
            return "READY", "good", rows
        minutes = config.estimator.estimate_minutes(status.percent, decision.cap)
        finish = now + timedelta(minutes=minutes)
        late = deadline is not None and finish > deadline.at
        rows.append(("full", _when(finish, now) + (" late" if late else "")))
        return "CHARGING", "bad" if late else "warn", rows

    if decision.plan and not decision.plan.already_ready:
        rows.append(("start", _when(decision.plan.start_at, now)))
    if status.percent > normal + 2:
        # A limit only stops charging; on AC power the battery holds, it does not drain.
        if status.plugged_in:
            rows.append(("drain", f"unplug to reach {normal:g}%"))
        return "ABOVE LIMIT", "muted", rows
    return "HOLDING", "good", rows


def build_snapshot(
    config: Config,
    status: BatteryStatus,
    now: datetime,
    history: list[tuple[datetime, float]],
    published: dict | None,
) -> Snapshot:
    decision = decide(config, status, now)
    state, tone, rows = summarize(config, status, decision, now)
    deadline = decision.deadline

    hours = float(NO_DEADLINE_HOURS)
    if deadline:
        hours = min((deadline.at - now).total_seconds() / 3600 + 0.1, 40.0)
    projection = simulate(
        config, now, hours=hours, start_percent=status.percent, step_minutes=5, away_hours=1
    )
    future = []
    window_start = None
    for step in projection.steps[1:]:
        if deadline and step.at > deadline.at:
            break  # the plan ends at the departure
        charging = step.decision.cap > config.normal_cap
        if charging and window_start is None and deadline and step.at <= deadline.at:
            window_start = step.at
        future.append((step.at, step.status.percent, charging))
    if decision.cap > config.normal_cap:
        window_start = now
    since = now - timedelta(hours=PAST_HOURS)
    past = [(at, pct) for at, pct in history if since <= at < now]

    return Snapshot(
        status=status,
        decision=decision,
        state=state,
        tone=tone,
        rows=rows,
        charging_now=decision.cap > config.normal_cap,
        runway=Runway(
            now=now,
            percent=status.percent,
            normal_cap=config.normal_cap,
            past=past,
            future=future,
            deadline=deadline.at if deadline else None,
            deadline_target=max(deadline.target_percent, config.normal_cap) if deadline else None,
            window_start=window_start,
        ),
        service=service_state(published, now),
    )
