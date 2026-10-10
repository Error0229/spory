"""Append-only charging history used to learn charge speed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from spory.hardware import BatteryStatus


@dataclass(frozen=True)
class BatterySample:
    at: datetime
    percent: float
    plugged_in: bool
    charging: bool

    @classmethod
    def from_status(cls, at: datetime, status: BatteryStatus) -> BatterySample:
        return cls(at, status.percent, status.plugged_in, status.charging)

    def to_json(self) -> str:
        return json.dumps(
            {
                "at": self.at.isoformat(),
                "percent": self.percent,
                "plugged_in": self.plugged_in,
                "charging": self.charging,
            }
        )

    @classmethod
    def from_json(cls, line: str) -> BatterySample:
        data = json.loads(line)
        return cls(
            datetime.fromisoformat(data["at"]),
            float(data["percent"]),
            bool(data["plugged_in"]),
            bool(data["charging"]),
        )


class HistoryLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, sample: BatterySample) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(sample.to_json() + "\n")

    def read(self) -> list[BatterySample]:
        if not self.path.exists():
            return []
        samples = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    samples.append(BatterySample.from_json(line))
                except (ValueError, KeyError, TypeError):
                    continue  # a torn final line after a crash is not fatal
        return samples
