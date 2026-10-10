"""Generic Windows charge control through the battery class driver.

Windows lets a program ask the battery to charge or discharge with
IOCTL_BATTERY_SET_INFORMATION (BatteryCharge / BatteryDischarge), but only
when the firmware advertises BATTERY_SET_CHARGE_SUPPORTED and
BATTERY_SET_DISCHARGE_SUPPORTED. Many consumer laptops (including the MSI
Prestige 14Evo B13M) advertise neither, so this backend is chosen only when
both flags are present. The cap is enforced in software: discharge at the cap,
charge again a few percent below it.

This backend has not been tested on hardware that supports it.
"""

from __future__ import annotations

from typing import Callable, Protocol

from spory.hardware import BatteryStatus, read_system_power_status

SET_CHARGE_SUPPORTED = 0x00000001
SET_DISCHARGE_SUPPORTED = 0x00000002
BATTERY_CHARGE = 1
BATTERY_DISCHARGE = 2
HYSTERESIS_PERCENT = 3

IOCTL_BATTERY_QUERY_TAG = 0x294040
IOCTL_BATTERY_QUERY_INFORMATION = 0x294044
IOCTL_BATTERY_SET_INFORMATION = 0x298048


class BatteryDevice(Protocol):
    path: str

    def capabilities(self) -> int: ...

    def set_level(self, level: int) -> None: ...


class Win32BatteryDevice:
    """One battery interface opened through SetupAPI and DeviceIoControl."""

    def __init__(self, path: str):
        self.path = path

    def _ioctl(self, code: int, in_buf, out_buf, write: bool = False) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        access = 0x80000000 | (0x40000000 if write else 0)  # GENERIC_READ | GENERIC_WRITE
        handle = kernel32.CreateFileW(self.path, access, 3, None, 3, 0x80, None)
        if handle in (None, wintypes.HANDLE(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            returned = wintypes.DWORD()
            ok = kernel32.DeviceIoControl(
                handle, code,
                ctypes.byref(in_buf) if in_buf is not None else None,
                ctypes.sizeof(in_buf) if in_buf is not None else 0,
                ctypes.byref(out_buf) if out_buf is not None else None,
                ctypes.sizeof(out_buf) if out_buf is not None else 0,
                ctypes.byref(returned), None,
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(handle)

    def _tag(self) -> int:
        from ctypes import wintypes

        wait, tag = wintypes.ULONG(0), wintypes.ULONG(0)
        self._ioctl(IOCTL_BATTERY_QUERY_TAG, wait, tag)
        return tag.value

    def capabilities(self) -> int:
        import ctypes
        from ctypes import wintypes

        class QUERY(ctypes.Structure):
            _fields_ = [("BatteryTag", wintypes.ULONG), ("InformationLevel", ctypes.c_int), ("AtRate", wintypes.LONG)]

        class INFO(ctypes.Structure):
            _fields_ = [
                ("Capabilities", wintypes.ULONG), ("Technology", ctypes.c_ubyte),
                ("Reserved", ctypes.c_ubyte * 3), ("Chemistry", ctypes.c_ubyte * 4),
                ("DesignedCapacity", wintypes.ULONG), ("FullChargedCapacity", wintypes.ULONG),
                ("DefaultAlert1", wintypes.ULONG), ("DefaultAlert2", wintypes.ULONG),
                ("CriticalBias", wintypes.ULONG), ("CycleCount", wintypes.ULONG),
            ]

        info = INFO()
        self._ioctl(IOCTL_BATTERY_QUERY_INFORMATION, QUERY(self._tag(), 0, 0), info)  # BatteryInformation
        return info.Capabilities

    def set_level(self, level: int) -> None:
        import ctypes
        from ctypes import wintypes

        class SET(ctypes.Structure):
            _fields_ = [("BatteryTag", wintypes.ULONG), ("InformationLevel", ctypes.c_int), ("Buffer", ctypes.c_ubyte * 4)]

        self._ioctl(IOCTL_BATTERY_SET_INFORMATION, SET(self._tag(), level), None, write=True)


def battery_devices() -> list[Win32BatteryDevice]:
    """Paths of all present batteries (GUID_DEVCLASS_BATTERY interfaces)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

    battery_class = GUID(0x72631E54, 0x78A4, 0x11D0, (ctypes.c_ubyte * 8)(0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A))
    info_set = setupapi.SetupDiGetClassDevsW(ctypes.byref(battery_class), None, None, 0x2 | 0x10)
    devices = []
    try:
        index = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA(cbSize=ctypes.sizeof(SP_DEVICE_INTERFACE_DATA))
            if not setupapi.SetupDiEnumDeviceInterfaces(info_set, None, ctypes.byref(battery_class), index, ctypes.byref(data)):
                break
            index += 1
            needed = wintypes.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(info_set, ctypes.byref(data), None, 0, ctypes.byref(needed), None)
            detail = ctypes.create_string_buffer(needed.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 on 64-bit, 6 on 32-bit.
            ctypes.cast(detail, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if setupapi.SetupDiGetDeviceInterfaceDetailW(info_set, ctypes.byref(data), detail, needed, None, None):
                devices.append(Win32BatteryDevice(ctypes.wstring_at(ctypes.addressof(detail) + 4)))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info_set)
    return devices


def supports_control(capabilities: int) -> bool:
    needed = SET_CHARGE_SUPPORTED | SET_DISCHARGE_SUPPORTED
    return capabilities & needed == needed


class WindowsDriverBattery:
    name = "windows battery driver"
    writable = True

    def __init__(
        self,
        device: BatteryDevice,
        read_status: Callable[[], BatteryStatus] = read_system_power_status,
    ):
        self.device = device
        self._read_status = read_status
        self.cap = 100.0
        self.level: int | None = None

    @classmethod
    def detect(cls) -> WindowsDriverBattery | None:
        for device in battery_devices():
            try:
                if supports_control(device.capabilities()):
                    return cls(device)
            except OSError:
                continue
        return None

    def read_status(self) -> BatteryStatus:
        return self._read_status()

    def read_charge_cap(self) -> float:
        return self.cap

    def set_charge_cap(self, percent: float) -> None:
        self.cap = percent
        self.maintain(self.read_status())

    def maintain(self, status: BatteryStatus) -> None:
        if self.cap >= 100 or status.percent <= self.cap - HYSTERESIS_PERCENT:
            wanted = BATTERY_CHARGE
        elif status.percent >= self.cap and status.plugged_in:
            wanted = BATTERY_DISCHARGE
        else:
            return  # inside the hysteresis band: keep the current level
        if wanted != self.level:
            self.device.set_level(wanted)
            self.level = wanted

    def close(self, normal_cap: float) -> None:
        # Never leave the battery forced to discharge after spory exits.
        if self.level != BATTERY_CHARGE:
            self.device.set_level(BATTERY_CHARGE)
            self.level = BATTERY_CHARGE
