import os
import unittest
from datetime import time

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
except ImportError:  # the GUI is optional
    QApplication = None

if QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from spory.gui.pickers import DaysField, NumberField, TimeField, Wheel

    APP = QApplication.instance() or QApplication([])


def wheel(widget, delta: int, modifiers=None):
    if modifiers is None:
        modifiers = Qt.KeyboardModifier.NoModifier
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta),
                        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    widget.wheelEvent(event)


@unittest.skipUnless(QApplication, "PySide6 not installed")
class NumberFieldTests(unittest.TestCase):
    def setUp(self):
        self.field = NumberField(0, 240, 15, "min", 110)
        self.seen = []
        self.field.changed.connect(self.seen.append)

    def test_typing_any_value_and_clamping(self):
        self.field.edit.setText("37")
        self.field._commit()
        self.assertEqual(self.field.value, 37)
        self.field.edit.setText("999")
        self.field._commit()
        self.assertEqual(self.field.value, 240)
        self.assertEqual(self.seen, [37, 240])

    def test_steppers_and_wheel(self):
        self.field.bump(1)
        self.assertEqual(self.field.value, 16)
        wheel(self.field, -120)
        self.assertEqual(self.field.value, 15)
        wheel(self.field, 120, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.field.value, 20)

    def test_minimum_disables_minus(self):
        self.field.set_value(0)
        self.assertFalse(self.field.minus.isEnabled())
        self.field.bump(-1)
        self.assertEqual(self.field.value, 0)
        self.assertEqual(self.seen, [])


@unittest.skipUnless(QApplication, "PySide6 not installed")
class WheelTests(unittest.TestCase):
    def test_steps_wrap_around(self):
        w = Wheel([f"{m:02d}" for m in range(60)], 58)
        w.step(3)
        self.assertEqual(w.index(), 1)
        w.step(-2)
        self.assertEqual(w.index(), 59)

    def test_time_field_sets_any_minute(self):
        field = TimeField(70, time(9, 30))
        field.open()
        field.hours.step(-2)
        field.minutes.step(7)
        self.assertEqual((field.hours.index(), field.minutes.index()), (7, 37))
        field.popup.close()


@unittest.skipUnless(QApplication, "PySide6 not installed")
class DaysFieldTests(unittest.TestCase):
    def test_toggles_make_custom_days(self):
        field = DaysField(110, "mon-fri")
        field.open()
        field._toggle(4)  # drop friday
        self.assertEqual(field.value, "mon,tue,wed,thu")
        field._toggle(4)
        self.assertEqual(field.text(), "weekdays")
        field.popup.close()


if __name__ == "__main__":
    unittest.main()
