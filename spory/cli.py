"""Command-line interface: `python -m spory <command>`."""

from __future__ import annotations

import argparse
import sys
import time as time_module
from datetime import date, datetime, time, timedelta

from spory.controller import decide
from spory.backends import driver_capabilities, select_backend
from spory import __version__
from spory.hardware import BatteryStatus, is_admin, read_system_power_status
from spory.reminders import notify
from spory.windows_driver import describe
from spory.history import BatterySample, HistoryLog
from spory.schedule import OneTimeDeadline, WeeklyRule, parse_weekdays
from spory.service import Service, refit
from spory.simulator import simulate
from spory.state import Config, Store


def now_local() -> datetime:
    return datetime.now().astimezone()


def parse_when(text: str, now: datetime) -> datetime:
    """"HH:MM" means its next occurrence; otherwise an ISO date-time."""
    try:
        at = time.fromisoformat(text)
    except ValueError:
        when = datetime.fromisoformat(text)
        return when if when.tzinfo else when.astimezone()
    when = datetime.combine(now.date(), at).astimezone()
    return when if when > now else datetime.combine(now.date() + timedelta(days=1), at).astimezone()


def parse_day(text: str, now: datetime) -> date:
    offsets = {"today": 0, "tomorrow": 1}
    if text in offsets:
        return now.date() + timedelta(days=offsets[text])
    return date.fromisoformat(text)


def percent(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return value


def minutes(text: str) -> float:
    value = float(text)
    if not 0 <= value < float("inf"):
        raise argparse.ArgumentTypeError("must be zero or more")
    return value


def positive(text: str) -> float:
    value = float(text)
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError("must be more than zero")
    return value


def fmt(at: datetime | None) -> str:
    return at.strftime("%a %Y-%m-%d %H:%M") if at else "-"


def read_status(args) -> BatteryStatus:
    if args.percent is not None:
        return BatteryStatus(args.percent, True, args.percent < 100)
    return read_system_power_status()


def cmd_status(store: Store, config: Config, args) -> int:
    now = now_local()
    status = read_status(args)
    decision = decide(config, status, now)
    plugged = "plugged in" if status.plugged_in else "on battery"
    charging = ", charging" if status.charging else ""
    print(f"Battery:        {status.percent:g}% ({plugged}{charging})")
    print(f"Normal cap:     {config.normal_cap:g}%")
    print(f"Cap right now:  {decision.cap:g}%  ({decision.reason})")
    d = decision.deadline
    print(f"Next deadline:  {fmt(d.at) + f' -> {d.target_percent:g}%' if d else 'none'}")
    if decision.plan and not decision.plan.already_ready:
        print(f"Charge starts:  {fmt(decision.plan.start_at)}")
        print(f"Expected full:  {fmt(decision.plan.estimated_finish)}")
    if not status.plugged_in and d:
        print("Note: plug in before the charge start for the plan to work.")
    return 0


def cmd_rule(store: Store, config: Config, args) -> int:
    rules = config.schedule.weekly
    if args.action == "add":
        if args.days is None or args.time is None:
            print("usage: spory rule add DAYS HH:MM [--target N]", file=sys.stderr)
            return 2
        rules.append(WeeklyRule(parse_weekdays(args.days), time.fromisoformat(args.time), args.target))
        store.save(config)
    elif args.action == "remove":
        if args.days is None or not args.days.isdigit() or not 1 <= int(args.days) <= len(rules):
            print("usage: spory rule remove N  (see `spory rule list`)", file=sys.stderr)
            return 2
        rules.pop(int(args.days) - 1)
        store.save(config)
    for i, rule in enumerate(rules, 1):
        print(f"{i}. {rule.describe()}")
    if not rules:
        print("no weekly rules")
    return 0


def cmd_once(store: Store, config: Config, args) -> int:
    now = now_local()
    if args.clear:
        config.schedule.one_time.clear()
        store.save(config)
        print("cleared one-time deadlines")
        return 0
    when = parse_when(args.when, now)
    if when <= now:
        print("deadline must be in the future", file=sys.stderr)
        return 2
    config.schedule.one_time.append(OneTimeDeadline(when, args.target))
    store.save(config)
    print(f"one-time deadline {fmt(when)} -> {args.target:g}%")
    return 0


def cmd_skip(store: Store, config: Config, args) -> int:
    day = parse_day(args.day, now_local())
    if args.undo:
        config.schedule.skip_dates.discard(day)
        print(f"weekly rules apply again on {day}")
    else:
        config.schedule.skip_dates.add(day)
        print(f"skipping weekly rules on {day}")
    store.save(config)
    return 0


def cmd_cap(store: Store, config: Config, args) -> int:
    if args.percent_value is not None:
        config.normal_cap = args.percent_value
    if args.margin is not None:
        config.safety_margin_minutes = args.margin
    store.save(config)
    print(f"normal cap {config.normal_cap:g}%, safety margin {config.safety_margin_minutes:g} min")
    return 0


def cmd_charge_now(store: Store, config: Config, args) -> int:
    now = now_local()
    if args.cancel:
        config.charge_now_until = None
        print("charge-now override cancelled")
    else:
        until = parse_when(args.until, now) if args.until else now + timedelta(hours=args.hours)
        config.charge_now_until = until
        print(f"charging to 100% until {fmt(until)}")
    store.save(config)
    return 0


def cmd_simulate(store: Store, config: Config, args) -> int:
    start = now_local().replace(second=0, microsecond=0)
    result = simulate(
        config, start, hours=args.hours, start_percent=args.start_percent, away_hours=args.away_hours
    )
    last = None
    for step in result.steps:
        key = (step.decision.cap, step.status.plugged_in)
        if key != last:
            where = "plugged" if step.status.plugged_in else "away"
            print(f"{fmt(step.at)}  {step.status.percent:5.1f}%  {where:7}  cap {step.decision.cap:g}%  {step.decision.reason}")
            last = key
    print()
    for d in result.deadlines:
        mark = "met" if d.met else "MISSED"
        print(f"deadline {fmt(d.deadline)}: {d.percent:g}% of {d.target_percent:g}% ({mark})")
    if not result.deadlines:
        print("no deadlines in the simulated period; add one with `spory rule add`")
    return 0 if all(d.met for d in result.deadlines) else 1


def cmd_log(store: Store, config: Config, args) -> int:
    history = HistoryLog(store.history_path)
    while True:
        sample = BatterySample.from_status(now_local(), read_system_power_status())
        history.append(sample)
        print(sample.to_json())
        if not args.watch:
            return 0
        time_module.sleep(args.interval)


def cmd_learn(store: Store, config: Config, args) -> int:
    samples = HistoryLog(store.history_path).read()
    estimator = refit(store)
    print(f"fitted from {len(samples)} samples; minutes per percent by band:")
    for i, rate in enumerate(estimator.minutes_per_percent):
        print(f"  {i * 10:3d}-{i * 10 + 10:3d}%  {rate:.2f}")
    print(f"estimate {config.normal_cap:g}% -> 100%: {estimator.estimate_minutes(config.normal_cap, 100):.0f} min")
    return 0


def cmd_run(store: Store, config: Config, args) -> int:
    if sys.stdout is None:
        # Started without a console (Task Scheduler, pythonw, packaged app): log to a file.
        store.home.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(store.home / "service.log", "a", buffering=1, encoding="utf-8")
    selection = select_backend(args.allow_unverified)
    for note in selection.notes:
        print(note)
    mode = " (dry run)" if args.dry_run and selection.adapter.writable else ""
    print(
        f"spory running with {selection.adapter.name} backend{mode}; "
        f"checking every {args.interval:g}s (Ctrl+C to stop)",
        flush=True,
    )
    service = Service(store, selection.adapter, dry_run=args.dry_run, notify=notify)
    try:
        service.run_forever(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_limit(store: Store, config: Config, args) -> int:
    selection = select_backend(args.allow_unverified)
    adapter = selection.adapter
    if not adapter.writable:
        for note in selection.notes:
            print(note)
        print("spory cannot set the charge limit on this PC", file=sys.stderr)
        return 1
    if args.percent_value is not None:
        adapter.set_charge_cap(args.percent_value)
    print(f"charge limit ({adapter.name}): {adapter.read_charge_cap():g}%")
    return 0


def cmd_diagnose(store: Store, config: Config, args) -> int:
    selection = select_backend(args.allow_unverified)
    print(f"Model:    {selection.manufacturer} {selection.model}")
    print(f"Admin:    {'yes' if selection.admin else 'no'}")
    for path, caps in driver_capabilities():
        if caps is None:
            print(f"Battery:  {path} (capabilities unavailable)")
        else:
            print(f"Battery:  {path} flags=0x{caps:08X} ({describe(caps)})")
    for note in selection.notes:
        print(f"  - {note}")
    print(f"Backend:  {selection.adapter.name}")
    return 0


def cmd_gui(store: Store, config: Config, args) -> int:
    try:
        from spory.gui.app import main as gui_main
    except ImportError:
        print("the GUI needs PySide6: pip install PySide6", file=sys.stderr)
        return 1
    return gui_main([sys.argv[0]] + (["--tray"] if args.tray else []))


def cmd_service(store: Store, config: Config, args) -> int:
    from spory import service_task

    if args.action == "status":
        print("installed" if service_task.is_installed() else "not installed")
        published = store.read_status()
        if published:
            print(f"last check {published.get('updated_at')} ({published.get('backend')})")
        return 0
    if not is_admin():
        code = service_task.run_elevated("service", args.action)
        if code is None:
            print("administrator approval was declined", file=sys.stderr)
            return 1
        return code
    if args.action == "install":
        service_task.register()
        print("background service installed and started")
    else:
        service_task.unregister()
        print("background service removed")
        try:
            print(service_task.restore_original_limit(store))
        except (OSError, RuntimeError) as exc:
            print(f"could not restore the charge limit: {exc}", file=sys.stderr)
    return 0


def cmd_update(store: Store, config: Config, args) -> int:
    from spory import updater

    release = updater.latest_release()
    if release is None:
        print("no release found (offline, or releases are not public yet)")
        return 1
    if not updater.is_newer(release.version):
        print(f"spory {__version__} is up to date")
        return 0
    print(f"spory {release.version} is available (installed {__version__})")
    if args.check:
        return 0
    path = updater.download(release)
    print(f"verified {path.name}; starting the installer")
    updater.launch_installer(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spory", description="Charge laptop battery by a deadline.")
    p.add_argument("--version", action="version", version=f"spory {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="show battery, next deadline and planned charge start")
    s.add_argument("--percent", type=percent, help="plan for this charge level instead of reading the battery")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("rule", help="list, add or remove weekly deadlines")
    s.add_argument("action", nargs="?", choices=["list", "add", "remove"], default="list")
    s.add_argument("days", nargs="?", help='e.g. "mon-fri", "sat,sun", "daily"; or rule number to remove')
    s.add_argument("time", nargs="?", help="departure time, HH:MM")
    s.add_argument("--target", type=percent, default=100)
    s.set_defaults(func=cmd_rule)

    s = sub.add_parser("once", help="add a one-time deadline")
    s.add_argument("when", nargs="?", default="", help="HH:MM (next occurrence) or YYYY-MM-DDTHH:MM")
    s.add_argument("--target", type=percent, default=100)
    s.add_argument("--clear", action="store_true", help="remove all one-time deadlines")
    s.set_defaults(func=cmd_once)

    s = sub.add_parser("skip", help="skip weekly deadlines on a date")
    s.add_argument("day", help="today, tomorrow or YYYY-MM-DD")
    s.add_argument("--undo", action="store_true")
    s.set_defaults(func=cmd_skip)

    s = sub.add_parser("cap", help="show or set the normal cap and safety margin")
    s.add_argument("percent_value", nargs="?", type=percent, metavar="PERCENT")
    s.add_argument("--margin", type=minutes, help="safety margin in minutes")
    s.set_defaults(func=cmd_cap)

    s = sub.add_parser("charge-now", help="charge to 100%% now, ignoring the cap for a while")
    s.add_argument("--hours", type=positive, default=3)
    s.add_argument("--until", help="HH:MM or YYYY-MM-DDTHH:MM")
    s.add_argument("--cancel", action="store_true")
    s.set_defaults(func=cmd_charge_now)

    s = sub.add_parser("simulate", help="replay the schedule against a simulated battery")
    s.add_argument("--hours", type=positive, default=48)
    s.add_argument("--start-percent", type=percent, default=60)
    s.add_argument("--away-hours", type=minutes, default=9, help="time unplugged after each deadline")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("log", help="record battery telemetry to the history file")
    s.add_argument("--watch", action="store_true", help="keep logging")
    s.add_argument("--interval", type=positive, default=60, help="seconds between samples")
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("learn", help="fit charge speed from recorded history")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("run", help="run the scheduler loop with the best available backend")
    s.add_argument("--interval", type=positive, default=60, help="seconds between checks")
    s.add_argument("--dry-run", action="store_true", help="log cap changes without applying them")
    s.add_argument("--allow-unverified", action="store_true", help="try the MSI backend on unverified MSI models")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("limit", help="show or set the firmware charge limit now (needs admin)")
    s.add_argument("percent_value", nargs="?", type=percent, metavar="PERCENT")
    s.add_argument("--allow-unverified", action="store_true")
    s.set_defaults(func=cmd_limit)

    s = sub.add_parser("diagnose", help="show which charge-control backend this PC supports")
    s.add_argument("--allow-unverified", action="store_true")
    s.set_defaults(func=cmd_diagnose)

    s = sub.add_parser("service", help="install, remove or check the background service")
    s.add_argument("action", choices=["install", "uninstall", "status"])
    s.set_defaults(func=cmd_service)

    s = sub.add_parser("update", help="download and install the latest release")
    s.add_argument("--check", action="store_true", help="only report whether an update exists")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("gui", help="open the desktop app (needs PySide6)")
    s.add_argument("--tray", action="store_true", help="start minimized to the tray")
    s.set_defaults(func=cmd_gui)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "once" and not args.clear and not args.when:
        print("usage: spory once WHEN [--target N] | spory once --clear", file=sys.stderr)
        return 2
    store = Store()
    try:
        return args.func(store, store.load(), args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"spory: {exc}", file=sys.stderr)
        return 1
