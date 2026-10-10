import re
import unittest
from datetime import datetime, timedelta, timezone

from spory.controller import Decision
from spory.hardware import BatteryStatus, ReadOnlyAdapterError
from spory.msi import MsiBattery, MsiError, decode_limit, encode_limit, is_msi
from spory.reminders import ReminderOnlyBattery, Reminders
from spory.schedule import Deadline
from spory.windows_driver import describe

UTC = timezone.utc


class FakeMsiFirmware:
    """Mimics MSI_ACPI Get_Data/Set_Data at address 0xD7."""

    def __init__(self, value=0xE4, ok=True):
        self.value = value
        self.ok = ok
        self.scripts = []

    def __call__(self, script):
        self.scripts.append(script)
        if not self.ok:
            return ""
        assert "$bytes[0] = 215" in script
        if "Set_Data" in script:
            self.value = int(re.search(r"\$bytes\[1\] = (\d+)", script).group(1))
        return f"bytes=1,{self.value}," + ",".join(["0"] * 30)


def plugged(percent):
    return lambda: BatteryStatus(percent, True, True)


class MsiTests(unittest.TestCase):
    def test_encoding(self):
        self.assertEqual(encode_limit(60), 0xBC)
        self.assertEqual(decode_limit(0xE4), 100)
        with self.assertRaises(ValueError):
            encode_limit(5)
        with self.assertRaises(MsiError):
            decode_limit(60)  # enabled bit missing: unknown layout

    def test_read_and_write_with_readback(self):
        fw = FakeMsiFirmware()
        msi = MsiBattery(runner=fw, read_status=plugged(70))
        self.assertEqual(msi.read_charge_cap(), 100)
        msi.set_charge_cap(80)
        self.assertEqual(fw.value, 0xD0)
        self.assertEqual(msi.read_charge_cap(), 80)
        msi.close(60)
        self.assertEqual(msi.read_charge_cap(), 60)

    def test_no_admin_output_is_an_error(self):
        with self.assertRaises(MsiError):
            MsiBattery(runner=FakeMsiFirmware(ok=False)).read_charge_cap()

    def test_manufacturer_detection(self):
        self.assertTrue(is_msi("Micro-Star International Co., Ltd."))
        self.assertFalse(is_msi("LENOVO"))


class WindowsDriverTests(unittest.TestCase):
    def test_describe_flags(self):
        self.assertEqual(describe(0x80000003), "set-charge, set-discharge")
        self.assertEqual(describe(0x80000000), "no set-information support")  # what the MSI laptop reports


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.deadline = Deadline(datetime(2026, 10, 2, 9, 30, tzinfo=UTC), 100, "rule")
        self.charge = Decision(100, "charging", self.deadline, None, None)
        self.hold = Decision(60, "holding", self.deadline, None, None)

    def test_plug_in_reminder_once_per_deadline(self):
        r = Reminders()
        self.assertIn("09:30", r.check(self.charge, BatteryStatus(55, False, False), 60))
        self.assertIsNone(r.check(self.charge, BatteryStatus(54, False, False), 60))
        self.assertIsNone(r.check(self.charge, BatteryStatus(56, True, True), 60))

    def test_unplug_reminder_rearms_after_unplugging(self):
        r = Reminders()
        self.assertIn("Unplug", r.check(self.hold, BatteryStatus(60, True, True), 60))
        self.assertIsNone(r.check(self.hold, BatteryStatus(61, True, True), 60))
        self.assertIsNone(r.check(self.hold, BatteryStatus(61, False, False), 60))
        self.assertIn("Unplug", r.check(self.hold, BatteryStatus(61, True, True), 60))

    def test_reminder_only_backend_refuses_writes(self):
        with self.assertRaises(ReadOnlyAdapterError):
            ReminderOnlyBattery(plugged(50)).set_charge_cap(80)


if __name__ == "__main__":
    unittest.main()
