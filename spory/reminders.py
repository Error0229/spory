"""Fallback for PCs whose charge limit spory cannot set: tell the user instead."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable

from spory.controller import Decision
from spory.hardware import BatteryStatus, ReadOnlyAdapterError, read_system_power_status, run_powershell


class ReminderOnlyBattery:
    name = "reminders only"
    writable = False

    def __init__(self, read_status: Callable[[], BatteryStatus] = read_system_power_status):
        self._read_status = read_status

    def read_status(self) -> BatteryStatus:
        return self._read_status()

    def read_charge_cap(self) -> float:
        return 100.0

    def set_charge_cap(self, percent: float) -> None:
        raise ReadOnlyAdapterError("this PC's charge limit cannot be set by spory")

    def maintain(self, status: BatteryStatus) -> None:
        pass

    def close(self, normal_cap: float) -> None:
        pass


class Reminders:
    """Turns decisions into plug/unplug reminders, each sent once per situation."""

    def __init__(self):
        self.plug_key: object = None
        self.unplug_armed = True

    def check(self, decision: Decision, status: BatteryStatus, normal_cap: float) -> str | None:
        if decision.cap > normal_cap:
            self.unplug_armed = True
            if status.plugged_in:
                return None
            key = decision.deadline.at if decision.deadline else "charge-now"
            if key == self.plug_key:
                return None
            self.plug_key = key
            if decision.deadline:
                return (
                    f"Plug in now to reach {decision.cap:g}% "
                    f"by {decision.deadline.at:%H:%M}."
                )
            return "Plug in now: charge-now override is on."
        if not status.plugged_in or status.percent < normal_cap:
            self.unplug_armed = True
            return None
        if self.unplug_armed:
            self.unplug_armed = False
            return (
                f"Battery at {status.percent:g}%. Unplug to keep it near {normal_cap:g}% "
                "and reduce wear."
            )
        return None


def notify(message: str, title: str = "spory") -> None:
    """Windows toast notification; elsewhere, print."""
    if sys.platform != "win32":
        print(f"[{title}] {message}", flush=True)
        return
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
$text.Item(0).AppendChild($xml.CreateTextNode('{title.replace("'", "''")}')) | Out-Null
$text.Item(1).AppendChild($xml.CreateTextNode('{message.replace("'", "''")}')) | Out-Null
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
    try:
        run_powershell(script, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass  # the run loop logs the reminder anyway
