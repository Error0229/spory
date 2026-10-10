# spory

Smart laptop power management tool for Windows. The first feature is **charge by deadline**: keep a normal battery cap while plugged in, then charge toward a requested target shortly before a chosen departure time.

Spory works on any Windows laptop and picks the best available way to control charging:

| Backend | When | How |
| --- | --- | --- |
| `msi` | MSI laptops | Sets the firmware charge limit through MSI's ACPI-WMI interface, the one MSI Center uses. Verified on the Prestige 14Evo B13M. |
| `windows battery driver` | Firmware advertises charge/discharge control | Enforces the cap in software through `IOCTL_BATTERY_SET_INFORMATION`. Not yet tested on supporting hardware. |
| `reminders only` | Everything else | Windows notifications: "plug in now to reach 100% by 09:30", "unplug to stay near 60%". |

> [!IMPORTANT]
> **A limit stops charging. It does not drain.** spory can stop charging at any level, but it cannot make the battery go down while the charger is plugged in. If the battery is above your limit, it stays there until you use the laptop unplugged.

## Install

Download `spory-setup-<version>.exe` from [Releases](https://github.com/Error0229/spory/releases) and run it. Setup asks for administrator approval once, then:

- installs spory to `Program Files` with a Start menu entry;
- starts the background service (an elevated Task Scheduler task that runs at sign-in);
- optionally starts spory in the tray when you sign in.

Windows may show a SmartScreen warning because the installer is not code-signed yet: choose **More info → Run anyway**.

**Update:** when a new release is out, an `update` button appears in spory's header (and under **settings → version**). It downloads the installer, checks its SHA-256, and upgrades in place; spory restarts on the new version with your settings kept. Running a newer `spory-setup` by hand does the same. From a terminal: `spory-cli update`.

**Uninstall:** Windows **Settings → Apps → Installed apps → spory → Uninstall**. This removes the background service, puts the battery charge limit back to what it was before spory first changed it, and asks whether to delete your settings and charge history (`%APPDATA%\spory`).

## Desktop app

The **dash** page shows the battery level, the state (`HOLDING`, `CHARGING`, `READY`, `ABOVE LIMIT`), the limit, next departure and charge start, and a chart from the last six hours to the departure. **Settings** holds the normal limit, safety margin, departures, the background service and updates. The app runs without admin rights: it edits `config.json`, and the elevated service applies changes within a minute and reports back through `status.json`.

## Command line

The installed app includes `spory-cli.exe`; from source, use `uv run spory`.

```bash
spory rule add mon-fri 09:30          # weekly departure, charge to 100%
spory rule add sat 11:00 --target 90
spory cap 60 --margin 15              # normal cap and safety margin
spory status                          # battery, next deadline, planned start and finish
spory once 07:15                      # one-time deadline (next 07:15, or YYYY-MM-DDTHH:MM)
spory skip tomorrow                   # ignore weekly rules for a day (--undo to revert)
spory charge-now --hours 2            # override: charge to 100% now (--cancel to stop)
spory simulate --hours 72             # replay the schedule against a simulated battery
spory learn                           # fit charge speed per 10% band from the history
spory service install|uninstall|status
spory update [--check]

# administrator terminal:
spory diagnose                        # which backend this PC supports, and why
spory limit [PERCENT]                 # show or set the firmware charge limit now
spory run [--dry-run]                 # the service loop itself
```

On MSI models other than the verified one, `run --allow-unverified` lets spory try the MSI backend; it reads the limit first and refuses values in an unexpected format.

Settings and history live in `%APPDATA%\spory` (`config.json`, `history.jsonl`, `service.log`). Set `SPORY_HOME` to use another directory.

## Development

Uses [uv](https://docs.astral.sh/uv/).

```bash
uv run python -m unittest discover -s tests -v   # tests
uv run --extra gui spory gui                     # desktop app from source
uv run --extra gui --group build python packaging/build.py   # dist/spory-setup-<version>.exe
```

Building the installer also needs Inno Setup (`scoop install extras/inno-setup`). To release, bump `__version__` in `spory/__init__.py` and push a matching tag (`v0.2.0`); the `release` workflow tests, builds and publishes the installer with its `.sha256`, which in-app updates require. In-app update checks use the public GitHub API, so they work once releases are public.

The planner, estimator, schedule, controller, simulator, updater and backends (with fake firmware and devices) are tested without hardware. Telemetry, `diagnose`, `limit` and `run` need Windows.
