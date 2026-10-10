"""MSI charge limit through MSI's ACPI-WMI interface (what MSI Center uses).

root/WMI MSI_ACPI.Get_Data / Set_Data take a 32-byte Package_32. Byte 0 is the
embedded-controller address, 0xD7 for the battery threshold; byte 1 carries the
limit as 0x80 | percent. The reply's byte 0 is 1 on success. This matches the
Linux msi-wmi-platform driver and was verified read-write on a Prestige 14Evo
B13M (BIOS E14F1IMS.517) on 2026-10-06. Needs administrator rights.
"""

from __future__ import annotations

import re
from typing import Callable

from spory.hardware import BatteryStatus, read_system_power_status, run_powershell

MSI_MANUFACTURER = "Micro-Star International Co., Ltd."
VERIFIED_MODELS = {"Prestige 14Evo B13M"}
BATTERY_ADDR = 0xD7
ENABLED_BIT = 0x80
MIN_PERCENT, MAX_PERCENT = 10, 100

_SCRIPT = """
$ErrorActionPreference = 'Stop'
$acpi = Get-CimInstance -Namespace root/WMI -ClassName MSI_ACPI | Select-Object -First 1
$bytes = [byte[]]::new(32); $bytes[0] = {addr}; $bytes[1] = {value}
$pkg = New-CimInstance -Namespace root/WMI -ClassName Package_32 -ClientOnly -Property @{{ Bytes = $bytes }}
$r = Invoke-CimMethod -InputObject $acpi -MethodName {method} -Arguments @{{ Data = $pkg }}
"bytes=$(($r.Data.Bytes) -join ',')"
"""


class MsiError(RuntimeError):
    pass


def is_msi(manufacturer: str) -> bool:
    return "micro-star" in manufacturer.lower() or manufacturer.strip().upper() == "MSI"


def decode_limit(value: int) -> int:
    percent = value & ~ENABLED_BIT
    if not value & ENABLED_BIT or not MIN_PERCENT <= percent <= MAX_PERCENT:
        raise MsiError(f"unexpected charge-limit byte {value}; this model may use another layout")
    return percent


def encode_limit(percent: float) -> int:
    value = round(percent)
    if not MIN_PERCENT <= value <= MAX_PERCENT:
        raise ValueError(f"MSI charge limit must be {MIN_PERCENT}-{MAX_PERCENT}%")
    return ENABLED_BIT | value


class MsiBattery:
    name = "msi"
    writable = True

    def __init__(
        self,
        runner: Callable[[str], str] = run_powershell,
        read_status: Callable[[], BatteryStatus] = read_system_power_status,
    ):
        self._runner = runner
        self._read_status = read_status

    def _call(self, method: str, value: int = 0) -> list[int]:
        out = self._runner(_SCRIPT.format(addr=BATTERY_ADDR, value=value, method=method))
        match = re.search(r"bytes=([\d,]+)", out)
        if not match:
            raise MsiError(f"{method} failed; is spory running as administrator?")
        data = [int(b) for b in match.group(1).split(",")]
        if data[0] != 1:
            raise MsiError(f"{method} reported failure (status {data[0]})")
        return data

    def read_status(self) -> BatteryStatus:
        return self._read_status()

    def read_charge_cap(self) -> float:
        return float(decode_limit(self._call("Get_Data")[1]))

    def set_charge_cap(self, percent: float) -> None:
        value = encode_limit(percent)
        self._call("Set_Data", value)
        readback = self._call("Get_Data")[1]
        if readback != value:
            raise MsiError(f"wrote charge limit {value} but read back {readback}")

    def maintain(self, status: BatteryStatus) -> None:
        pass  # the firmware enforces the limit itself

    def close(self, normal_cap: float) -> None:
        self.set_charge_cap(normal_cap)
