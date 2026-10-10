"""The background service as an elevated Task Scheduler task.

Works both from a source checkout (pythonw -m spory run) and from the
packaged app (spory.exe run). Registering needs administrator rights; when
not elevated, the request is re-launched through a UAC prompt.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

from spory.state import Store

TASK_NAME = "spory"
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _pythonw() -> Path:
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return windowless if windowless.exists() else exe


def task_action() -> tuple[str, str, str]:
    """(program, arguments, working directory) the task starts at sign-in."""
    if frozen():
        exe = Path(sys.executable).with_name("spory.exe")
        return str(exe), "run", str(exe.parent)
    return str(_pythonw()), "-m spory run", str(SOURCE_ROOT)


def cli_command(*args: str) -> tuple[str, str, str]:
    """How to run `spory <args>` without a console window, for elevation."""
    if frozen():
        return sys.executable, " ".join(args), str(Path(sys.executable).parent)
    return str(_pythonw()), "-m spory " + " ".join(args), str(SOURCE_ROOT)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def register_script() -> str:
    program, arguments, workdir = task_action()
    user = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}".lstrip("\\")
    return f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_quote(program)} -Argument {_quote(arguments)} -WorkingDirectory {_quote(workdir)}
$trigger = New-ScheduledTaskTrigger -AtLogOn -User {_quote(user)}
$principal = New-ScheduledTaskPrincipal -UserId {_quote(user)} -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
Stop-ScheduledTask -TaskName {_quote(TASK_NAME)} -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName {_quote(TASK_NAME)} -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName {_quote(TASK_NAME)}
"""


def unregister_script() -> str:
    return f"""
Stop-ScheduledTask -TaskName {_quote(TASK_NAME)} -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName {_quote(TASK_NAME)} -Confirm:$false -ErrorAction SilentlyContinue
"""


def _powershell(script: str) -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell failed")


def register() -> None:
    """Create or replace the task and start it. Needs administrator rights."""
    _powershell(register_script())


def unregister() -> None:
    """Stop and delete the task. Needs administrator rights."""
    _powershell(unregister_script())


def is_installed() -> bool:
    result = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0


def restore_original_limit(store: Store) -> str:
    """Put the firmware charge limit back to what it was before spory changed it."""
    from spory.backends import select_backend

    config = store.load()
    target = config.original_limit if config.original_limit is not None else 100.0
    adapter = select_backend().adapter
    if not adapter.writable:
        return "no charge limit to restore"
    adapter.set_charge_cap(target)
    return f"charge limit restored to {target:g}%"


def run_elevated(*args: str, wait: bool = True) -> int | None:
    """Run `spory <args>` through a UAC prompt.

    Returns the exit code when waiting, 0 when not waiting, None if declined.
    """
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    program, arguments, workdir = cli_command(*args)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = program
    info.lpParameters = arguments
    info.lpDirectory = workdir
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return None  # declined at the UAC prompt
    if not wait:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
        return 0
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return code.value
