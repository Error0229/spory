"""Weekly and one-time charge deadlines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAYS = frozenset(range(5))


def parse_weekdays(text: str) -> frozenset[int]:
    """Parse "mon-fri", "weekdays", "sat,sun" or "daily" into weekday numbers."""
    text = text.strip().lower()
    aliases = {"weekdays": "mon-fri", "weekends": "sat,sun", "daily": "mon-sun"}
    text = aliases.get(text, text)
    days: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            first, last = (WEEKDAY_NAMES.index(p.strip()[:3]) for p in part.split("-"))
            span = (last - first) % 7
            days.update((first + i) % 7 for i in range(span + 1))
        else:
            days.add(WEEKDAY_NAMES.index(part[:3]))
    if not days:
        raise ValueError("no weekdays given")
    return frozenset(days)


def format_weekdays(days: frozenset[int]) -> str:
    if days == WEEKDAYS:
        return "mon-fri"
    if days == frozenset(range(7)):
        return "daily"
    return ",".join(WEEKDAY_NAMES[d] for d in sorted(days))


def localize(day: date, at: time, tz: tzinfo | None) -> datetime:
    """Attach a timezone; None means the system zone, honoring DST."""
    naive = datetime.combine(day, at)
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


@dataclass(frozen=True)
class WeeklyRule:
    weekdays: frozenset[int]
    at: time
    target_percent: float = 100

    def describe(self) -> str:
        return f"{format_weekdays(self.weekdays)} {self.at:%H:%M} -> {self.target_percent:g}%"


@dataclass(frozen=True)
class OneTimeDeadline:
    at: datetime
    target_percent: float = 100


@dataclass(frozen=True)
class Deadline:
    at: datetime
    target_percent: float
    source: str


@dataclass
class Schedule:
    weekly: list[WeeklyRule] = field(default_factory=list)
    one_time: list[OneTimeDeadline] = field(default_factory=list)
    skip_dates: set[date] = field(default_factory=set)
    tz: tzinfo | None = None

    def _today(self, now: datetime) -> date:
        return (now.astimezone(self.tz) if self.tz else now.astimezone()).date()

    def upcoming(self, now: datetime, days: int = 8) -> list[Deadline]:
        """Future deadlines in order, skipping weekly rules on skipped dates."""
        found = [
            Deadline(o.at, o.target_percent, "one-time")
            for o in self.one_time
            if o.at > now
        ]
        today = self._today(now)
        for offset in range(days):
            day = today + timedelta(days=offset)
            if day in self.skip_dates:
                continue
            for rule in self.weekly:
                if day.weekday() in rule.weekdays:
                    at = localize(day, rule.at, self.tz)
                    if at > now:
                        found.append(Deadline(at, rule.target_percent, rule.describe()))
        found.sort(key=lambda d: (d.at, -d.target_percent))
        return found

    def next_deadline(self, now: datetime) -> Deadline | None:
        upcoming = self.upcoming(now)
        return upcoming[0] if upcoming else None

    def prune(self, now: datetime) -> None:
        """Drop one-time deadlines and skip dates that are in the past."""
        self.one_time = [o for o in self.one_time if o.at > now]
        today = self._today(now)
        self.skip_dates = {d for d in self.skip_dates if d >= today}
