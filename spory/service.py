"""The long-running loop: read telemetry, log it, decide, apply."""

from __future__ import annotations

import time as time_module
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from spory.controller import Decision, decide
from spory.estimator import ChargeEstimator
from spory.hardware import BatteryAdapter, BatteryStatus
from spory.history import BatterySample, HistoryLog
from spory.reminders import Reminders
from spory.state import Store

REFIT_INTERVAL = timedelta(hours=1)


def refit(store: Store) -> ChargeEstimator:
    """Fit the full history against the default curve, then save.

    Always starting from the default avoids counting old history twice.
    """
    config = store.load()
    config.estimator = ChargeEstimator.fit(HistoryLog(store.history_path).read())
    store.save(config)
    return config.estimator


@dataclass
class TickResult:
    decision: Decision
    applied: bool
    message: str


class Service:
    def __init__(
        self,
        store: Store,
        adapter: BatteryAdapter,
        dry_run: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        notify: Callable[[str], None] = print,
    ):
        self.store = store
        self.adapter = adapter
        self.dry_run = dry_run
        self.clock = clock
        self.notify = notify
        self.history = HistoryLog(store.history_path)
        self.reminders = Reminders()
        self.last_message = ""
        self.last_fit: datetime | None = None

    def tick(self) -> TickResult:
        now = self.clock()
        if self.last_fit is None or now - self.last_fit >= REFIT_INTERVAL:
            refit(self.store)
            self.last_fit = now

        config = self.store.load()
        loaded = config.to_dict()
        config.schedule.prune(now)
        if config.charge_now_until and now >= config.charge_now_until:
            config.charge_now_until = None
        if self.adapter.writable and not self.dry_run and config.original_limit is None:
            config.original_limit = self.adapter.read_charge_cap()
        status = self.adapter.read_status()
        self.history.append(BatterySample.from_status(now, status))
        decision = decide(config, status, now)
        config.active = decision.active
        # Save only real changes so edits made in the GUI meanwhile are not overwritten.
        if config.to_dict() != loaded:
            self.store.save(config)
        result = self._apply(decision, status, config.normal_cap)
        self.store.publish_status(
            {
                "updated_at": now.isoformat(),
                "backend": self.adapter.name,
                "writable": self.adapter.writable,
                "dry_run": self.dry_run,
                "cap": decision.cap,
                "reason": decision.reason,
            }
        )
        return result

    def _apply(self, decision: Decision, status: BatteryStatus, normal_cap: float) -> TickResult:
        if not self.adapter.writable:
            reminder = self.reminders.check(decision, status, normal_cap)
            if reminder:
                self.notify(reminder)
            return TickResult(decision, False, f"reminder: {reminder}" if reminder else "")

        if self.dry_run:
            message = f"dry run: would set cap to {decision.cap:g}%"
            if message == self.last_message:
                return TickResult(decision, False, "")
            self.last_message = message
            return TickResult(decision, False, message)

        # Re-read every tick so a limit changed elsewhere (e.g. MSI Center) is corrected.
        current = self.adapter.read_charge_cap()
        changed = round(current) != round(decision.cap)
        if changed:
            self.adapter.set_charge_cap(decision.cap)
        self.adapter.maintain(status)
        message = f"set cap {current:g}% -> {decision.cap:g}%" if changed else ""
        return TickResult(decision, changed, message)

    def close(self) -> None:
        """Restore the normal cap so the battery is protected while spory is off."""
        if self.adapter.writable and not self.dry_run:
            self.adapter.close(self.store.load().normal_cap)

    def run_forever(self, interval_seconds: float = 60, log: Callable[[str], None] | None = None) -> None:
        """Poll on a fixed interval; after sleep or resume the next tick catches up."""
        log = log or (lambda line: print(line, flush=True))
        try:
            while True:
                try:
                    result = self.tick()
                    stamp = self.clock().strftime("%Y-%m-%d %H:%M")
                    if result.message:
                        log(f"{stamp} {result.message} ({result.decision.reason})")
                except (OSError, RuntimeError) as exc:
                    log(f"error: {exc}")
                time_module.sleep(interval_seconds)
        finally:
            self.close()
