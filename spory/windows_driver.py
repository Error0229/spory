"""Read-only battery capability flags from the Windows battery class driver.

IOCTL_BATTERY_SET_INFORMATION offers BatteryCharge and BatteryDischarge, but no
"stop charging". BatteryDischarge makes the battery power the PC even on AC, so
using it to enforce a cap would drain the battery and cycle it while plugged in.
spory therefore never writes through this interface; it only reports the flags
in `spory diagnose`.
"""

from __future__ import annotations

SET_CHARGE_SUPPORTED = 0x00000001
SET_DISCHARGE_SUPPORTED = 0x00000002

IOCTL_BATTERY_QUERY_TAG = 0x294040
IOCTL_BATTERY_QUERY_INFORMATION = 0x294044


class Win32BatteryDevice:
    """One battery interface opened through SetupAPI and DeviceIoControl."""

    def __init__(self, path: str):
        self.path = path

    def _ioctl(self, code: int, in_buf, out_buf) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
        ]
        handle = kernel32.CreateFileW(self.path, 0x80000000, 3, None, 3, 0x80, None)  # GENERIC_READ
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


def describe(capabilities: int) -> str:
    """The set-information flags the firmware advertises, for diagnosis."""
    flags = [name for bit, name in ((SET_CHARGE_SUPPORTED, "set-charge"), (SET_DISCHARGE_SUPPORTED, "set-discharge"))
             if capabilities & bit]
    return ", ".join(flags) if flags else "no set-information support"
