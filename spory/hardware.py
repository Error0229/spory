"""Battery adapter interface, the simulated battery and shared Windows helpers."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spory.estimator import ChargeEstimator


@dataclass(frozen=True)
class BatteryStatus:
    percent: float
    plugged_in: bool
    charging: bool


class ReadOnlyAdapterError(RuntimeError):
    """Raised when asked to change the charge cap on a read-only adapter."""


class BatteryAdapter(Protocol):
    name: str
    # False when the backend can only read the battery and remind the user.
    writable: bool

    def read_status(self) -> BatteryStatus: ...

    def read_charge_cap(self) -> float: ...

    def set_charge_cap(self, percent: float) -> None: ...

    def maintain(self, status: BatteryStatus) -> None:
        """Called every tick; backends that enforce the cap in software act here."""

    def close(self, normal_cap: float) -> None:
        """Leave the hardware in a safe state when spory stops."""


class SimulatedBattery:
    """A battery that charges along the estimator's curve up to a cap."""

    name = "simulated"
    writable = True

    def __init__(
        self,
        estimator: ChargeEstimator,
        percent: float = 60,
        cap: float = 60,
        plugged_in: bool = True,
        drain_percent_per_hour: float = 8,
    ):
        self.estimator = estimator
        self.percent = percent
        self.cap = cap
        self.plugged_in = plugged_in
        self.drain_percent_per_hour = drain_percent_per_hour

    def read_status(self) -> BatteryStatus:
        return BatteryStatus(
            round(self.percent, 2), self.plugged_in, self.plugged_in and self.percent < self.cap
        )

    def read_charge_cap(self) -> float:
        return self.cap

    def set_charge_cap(self, percent: float) -> None:
        self.cap = percent

    def maintain(self, status: BatteryStatus) -> None:
        pass

    def close(self, normal_cap: float) -> None:
        self.cap = normal_cap

    def advance(self, minutes: float) -> None:
        if not self.plugged_in:
            self.percent = max(0.0, self.percent - self.drain_percent_per_hour * minutes / 60)
            return
        # Lowering the cap never discharges a battery that is already above it.
        while minutes > 0 and self.percent < self.cap:
            rate = self.estimator.rate_at(self.percent)
            step = min(minutes / rate, self.cap - self.percent, 1.0)
            self.percent += step
            minutes -= step * rate


def require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("real battery access is only implemented for Windows")


def read_system_power_status() -> BatteryStatus:
    """Percent, AC state and charging flag from GetSystemPowerStatus (any Windows PC)."""
    require_windows()
    import ctypes
    from ctypes import wintypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    status = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise OSError("GetSystemPowerStatus failed")
    flag = status.BatteryFlag & 0xFF
    percent = status.BatteryLifePercent & 0xFF
    if flag == 0xFF or flag & 0x80 or percent == 0xFF:
        raise OSError("no battery reported by Windows")
    return BatteryStatus(float(percent), status.ACLineStatus == 1, bool(flag & 0x08))


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def system_model() -> tuple[str, str]:
    """(manufacturer, product name) as reported by the firmware."""
    require_windows()
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
        manufacturer = winreg.QueryValueEx(key, "SystemManufacturer")[0]
        product = winreg.QueryValueEx(key, "SystemProductName")[0]
    return str(manufacturer).strip(), str(product).strip()


def run_powershell(script: str, timeout: float = 60) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.stdout
