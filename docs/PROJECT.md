# Spory: charge by deadline

## Goal

While plugged in, keep the battery at a user-selected normal cap (for example, MSI's 50–60% mode). On weekdays, reach 100% shortly before the user's 09:30 departure. Allow one-time overrides and show the planned charging start time.

Spory should work on any Windows laptop. Charge-limit control is not standardized on Windows: the generic battery-driver interface is only implemented by some firmware, and most vendors expose their own interface. So control is split into backends (vendor, generic Windows driver, reminders only), and every PC gets at least reminders. The first verified machine is the owner's MSI Prestige 14Evo B13M. Do not enable writes for a model whose layout has not been checked.

## Planning rule

Given charge estimate E(current %, target %), deadline D, and safety margin M:

    start = D - E - M

Recalculate when the battery state, power connection, or rule changes. If the start has passed, charge immediately and report that the deadline may be missed. Restoring a 60% cap after departure does not discharge an already full battery.

## Architecture

- Pure planner, independent of Windows and MSI.
- Charge history estimator that accounts for slowdown near 100%.
- Persistent scheduler for weekly and one-time deadlines, power and sleep/wake events.
- Hardware adapter interface with simulation first; explicitly validate model and firmware before enabling writes.
- UI for next deadline, expected finish, normal cap, and charge-now override.

## Development order

1. Testable planner and simulator in the cloud. **Done.**
2. Windows read-only battery telemetry and charging-history collection. **Done.**
3. Investigate supported MSI Center or ACPI/WMI control for this exact model. **Done** (findings below).
4. Only then add reversible hardware writes and test on the owner's laptop. **Done** for MSI; generic Windows driver backend written but untested on supporting hardware.
5. More vendor backends (Lenovo, Dell, HP, ASUS, ...). **Not started.**

## Module map

| Module | Role |
| --- | --- |
| `planner.py` | `start = D - E - M`, late and already-ready detection |
| `estimator.py` | Minutes per percent in 10% bands (slower above 80%), fitted from history |
| `schedule.py` | Weekly rules, one-time deadlines, skip dates; local time with DST |
| `controller.py` | Pure decision of the cap to apply now; keeps an open charge window so the cap does not flap as the battery fills |
| `hardware.py` | `BatteryAdapter` interface, simulated battery, `GetSystemPowerStatus`, admin and model detection |
| `msi.py` | MSI backend: `MSI_ACPI.Get_Data` / `Set_Data` at EC address `0xD7` |
| `windows_driver.py` | Generic backend: `IOCTL_BATTERY_SET_INFORMATION` charge/discharge with hysteresis |
| `reminders.py` | Fallback backend: plug/unplug reminders as Windows toasts |
| `backends.py` | Chooses vendor, then generic driver, then reminders |
| `service.py` | Loop: read telemetry, append history, refit hourly, decide, apply, correct drift, restore normal cap on exit |
| `simulator.py` | Replays the controller against the simulated battery |
| `state.py`, `history.py` | JSON config and JSONL history in `%APPDATA%\spory` |
| `cli.py` | `spory status / rule / once / skip / cap / charge-now / simulate / log / learn / run / limit / diagnose` |

## Findings on the owner's laptop (2026-10-06)

- Model `Micro-Star International Co., Ltd.` / `Prestige 14Evo B13M`, BIOS `E14F1IMS.517`. Design capacity 70.0 Wh, full charge 46.6 Wh.
- The battery driver reports capabilities `0x80000000` (system battery only), so the generic Windows driver backend cannot control this laptop.
- MSI exposes `root/WMI` `MSI_ACPI`; its methods take and return a 32-byte `Package_32` and need administrator rights. `Get_MasterBattery` returns `1,3,...`, which is not the threshold.
- The threshold is `Get_Data` / `Set_Data` with byte 0 = `0xD7` and byte 1 = `0x80 | percent`; reply byte 0 is `1` on success. Address `0xEF` reads 0 on this model. Same layout as the Linux `msi-wmi-platform` driver.
- Verified write: setting 80% (`0xD0`) at 98% charge stopped charging within 20 s; restoring 100% (`0xE4`) resumed it. MSI Center did not override the value during the test. `spory run` then set and kept a 70% normal cap, and left it in place on exit.

## Known gaps

1. Wake from sleep is not handled: the loop catches up on resume, and the MSI firmware keeps enforcing the last limit while asleep. To hit a morning deadline while the laptop sleeps overnight, a Task Scheduler wake timer before the planned start is needed.
2. If MSI Center changes the limit when its battery mode is changed, spory corrects it within a minute; using both at once is not recommended.
3. Other vendors fall back to reminders until a backend is written and verified on real hardware.

A cloud Linux environment cannot test actual MSI battery controls or Windows wake timers. A powered-off machine cannot run the scheduler.
