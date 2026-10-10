"""Pick the best way to control charging on this PC.

Order: a vendor backend (MSI today), then the generic Windows battery driver,
then reminders only. Any Windows laptop gets at least the reminders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spory.hardware import BatteryAdapter, is_admin, require_windows, system_model
from spory.msi import VERIFIED_MODELS, MsiBattery, MsiError, is_msi
from spory.reminders import ReminderOnlyBattery
from spory.windows_driver import WindowsDriverBattery, battery_devices


@dataclass
class Selection:
    adapter: BatteryAdapter
    manufacturer: str
    model: str
    admin: bool
    notes: list[str] = field(default_factory=list)


def select_backend(allow_unverified: bool = False) -> Selection:
    require_windows()
    manufacturer, model = system_model()
    admin = is_admin()
    notes: list[str] = []

    if is_msi(manufacturer):
        verified = model in VERIFIED_MODELS
        if not admin:
            notes.append("MSI: run as administrator to control the charge limit")
        elif not verified and not allow_unverified:
            notes.append(
                f"MSI: {model} is not verified; rerun with --allow-unverified to try it "
                "(spory reads the limit first and refuses unexpected values)"
            )
        else:
            msi = MsiBattery()
            try:
                limit = msi.read_charge_cap()
                notes.append(f"MSI: current firmware charge limit {limit:g}%")
                return Selection(msi, manufacturer, model, admin, notes)
            except (MsiError, OSError) as exc:
                notes.append(f"MSI: not usable ({exc})")

    if admin:
        try:
            driver = WindowsDriverBattery.detect()
        except OSError as exc:
            driver = None
            notes.append(f"Windows battery driver: query failed ({exc})")
        if driver:
            notes.append("Windows battery driver: firmware supports charge/discharge control")
            return Selection(driver, manufacturer, model, admin, notes)
        notes.append("Windows battery driver: firmware does not support charge control")
    else:
        notes.append("Windows battery driver: run as administrator to use it if supported")

    notes.append("falling back to plug/unplug reminders")
    return Selection(ReminderOnlyBattery(), manufacturer, model, admin, notes)


def driver_capabilities() -> list[tuple[str, int | None]]:
    """Read-only capability flags of each battery, for diagnosis."""
    results = []
    for device in battery_devices():
        try:
            results.append((device.path, device.capabilities()))
        except OSError:
            results.append((device.path, None))
    return results

