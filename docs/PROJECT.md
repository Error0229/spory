# Spory: charge by deadline

## Goal

While plugged in, keep the battery at a user-selected normal cap (for example, MSI's 50–60% mode). On weekdays, reach 100% shortly before the user's 09:30 departure. Allow one-time overrides and show the planned charging start time.

The first supported machine to investigate is the MSI Prestige 14 Evo B13M. Hardware compatibility is **unverified**. Do not write embedded-controller registers based on another model's mapping.

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

1. Testable planner and simulator in the cloud.
2. Windows read-only battery telemetry and charging-history collection.
3. Investigate supported MSI Center or ACPI/WMI control for this exact model.
4. Only then add reversible hardware writes and test on the owner's laptop.

A cloud Linux environment cannot test actual MSI battery controls or Windows wake timers. A powered-off machine cannot run the scheduler.
