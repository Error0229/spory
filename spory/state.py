"""Persistent settings, schedule and controller state as JSON."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from spory.estimator import ChargeEstimator
from spory.schedule import (
    OneTimeDeadline,
    Schedule,
    WeeklyRule,
    format_weekdays,
    parse_weekdays,
)


def default_home() -> Path:
    if "SPORY_HOME" in os.environ:
        return Path(os.environ["SPORY_HOME"])
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "spory"


@dataclass(frozen=True)
class ActiveWindow:
    """A deadline whose charging has started; kept until the deadline passes.

    Without this, the rising charge level would shorten the estimate, push the
    planned start into the future and make the cap flap on and off.
    """

    deadline: datetime
    target_percent: float


@dataclass
class Config:
    normal_cap: float = 60
    safety_margin_minutes: float = 15
    schedule: Schedule = field(default_factory=Schedule)
    charge_now_until: datetime | None = None
    active: ActiveWindow | None = None
    estimator: ChargeEstimator = field(default_factory=ChargeEstimator)
    # Firmware limit found before spory first changed it; restored on uninstall.
    original_limit: float | None = None
    # The desktop app shows the "limit does not drain" notice once.
    notice_seen: bool = False

    def to_dict(self) -> dict:
        s = self.schedule
        return {
            "normal_cap": self.normal_cap,
            "safety_margin_minutes": self.safety_margin_minutes,
            "weekly": [
                {
                    "days": format_weekdays(r.weekdays),
                    "time": r.at.strftime("%H:%M"),
                    "target": r.target_percent,
                }
                for r in s.weekly
            ],
            "one_time": [
                {"at": o.at.isoformat(), "target": o.target_percent} for o in s.one_time
            ],
            "skip_dates": sorted(d.isoformat() for d in s.skip_dates),
            "charge_now_until": self.charge_now_until.isoformat()
            if self.charge_now_until
            else None,
            "active": {
                "deadline": self.active.deadline.isoformat(),
                "target": self.active.target_percent,
            }
            if self.active
            else None,
            "minutes_per_percent": self.estimator.minutes_per_percent,
            "original_limit": self.original_limit,
            "notice_seen": self.notice_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        schedule = Schedule(
            weekly=[
                WeeklyRule(
                    parse_weekdays(r["days"]),
                    time.fromisoformat(r["time"]),
                    float(r.get("target", 100)),
                )
                for r in data.get("weekly", [])
            ],
            one_time=[
                OneTimeDeadline(datetime.fromisoformat(o["at"]), float(o.get("target", 100)))
                for o in data.get("one_time", [])
            ],
            skip_dates={date.fromisoformat(d) for d in data.get("skip_dates", [])},
        )
        until = data.get("charge_now_until")
        active = data.get("active")
        rates = data.get("minutes_per_percent")
        return cls(
            normal_cap=float(data.get("normal_cap", 60)),
            safety_margin_minutes=_margin(data.get("safety_margin_minutes", 15)),
            schedule=schedule,
            charge_now_until=datetime.fromisoformat(until) if until else None,
            active=ActiveWindow(datetime.fromisoformat(active["deadline"]), float(active["target"]))
            if active
            else None,
            estimator=ChargeEstimator(list(rates)) if rates else ChargeEstimator(),
            original_limit=float(data["original_limit"]) if data.get("original_limit") is not None else None,
            notice_seen=bool(data.get("notice_seen", False)),
        )


def _margin(value) -> float:
    """A hand-edited negative or infinite margin would stop the planner; fall back to the default."""
    value = float(value)
    return value if 0 <= value < float("inf") else 15.0


class Store:
    def __init__(self, home: Path | None = None):
        self.home = home or default_home()
        self.config_path = self.home / "config.json"
        self.history_path = self.home / "history.jsonl"
        self.status_path = self.home / "status.json"

    def load(self) -> Config:
        if not self.config_path.exists():
            return Config()
        return Config.from_dict(json.loads(self.config_path.read_text(encoding="utf-8")))

    def save(self, config: Config) -> None:
        self._write(self.config_path, config.to_dict())

    def publish_status(self, status: dict) -> None:
        """What the background service last did, for the GUI to show."""
        self._write(self.status_path, status)

    def read_status(self) -> dict | None:
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, path: Path, data: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
