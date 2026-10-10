"""Themed inputs: a days picker, a scrolling-wheel time picker and number boxes."""

from __future__ import annotations

import math
from datetime import time

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QIntValidator, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spory.gui import theme as t
from spory.schedule import format_weekdays, parse_weekdays

PRESETS = [("weekdays", "mon-fri"), ("every day", "daily"), ("weekends", "sat,sun"), ("once", "once")]
DAY_NAMES = {value: text for text, value in PRESETS}
DAY_SHORT = ["mo", "tu", "we", "th", "fr", "sa", "su"]


def _set_active(widget: QWidget, active: bool) -> None:
    widget.setProperty("active", "true" if active else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def chip(text: str, active: bool = False, width: int | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", "chip")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFont(t.font(t.MONO, 10))
    b.setFixedHeight(28)
    if width:
        b.setFixedWidth(width)
    _set_active(b, active)
    return b


class Popup(QWidget):
    """A frameless panel under its field; closes when you click anywhere else."""

    hidden = Signal()

    def __init__(self, anchor: QWidget):
        super().__init__(anchor, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        panel = QFrame(self)
        panel.setProperty("role", "popup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        self.body = QVBoxLayout(panel)
        self.body.setContentsMargins(8, 8, 8, 8)
        self.body.setSpacing(8)

    def open_at(self, anchor: QWidget) -> None:
        self.adjustSize()
        area = anchor.screen().availableGeometry()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        if pos.y() + self.height() > area.bottom():
            pos.setY(anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4)
        pos.setX(min(pos.x(), area.right() - self.width()))
        self.move(pos)
        self.show()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.hidden.emit()


class PickerField(QPushButton):
    """Looks like an input box with its value centred; click to open a picker."""

    changed = Signal(object)

    def __init__(self, width: int, value=None):
        super().__init__()
        self.setProperty("kind", "field")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(width, 30)
        self.value = None
        self.popup: Popup | None = None
        self.clicked.connect(self.open)
        if value is not None:
            self.set_value(value)

    def display(self, value) -> str:
        return str(value)

    def set_value(self, value) -> None:
        self.value = value
        self.setText(self.display(value))

    def pick(self, value, close: bool = True) -> None:
        self.set_value(value)
        self.changed.emit(value)
        if close and self.popup:
            self.popup.close()

    def open(self) -> None:
        self.popup = Popup(self)
        self.popup.hidden.connect(lambda: _set_active(self, False))
        self.fill(self.popup.body)
        _set_active(self, True)
        self.popup.open_at(self)

    def fill(self, body: QVBoxLayout) -> None:
        raise NotImplementedError


class DaysField(PickerField):
    """Presets plus seven day toggles. Values: "mon-fri", "daily", "sat,sun", "once" or e.g. "mon,wed"."""

    def display(self, value: str) -> str:
        return DAY_NAMES.get(value, value)

    def _days(self) -> set[int]:
        return set() if self.value == "once" else set(parse_weekdays(self.value))

    def fill(self, body: QVBoxLayout) -> None:
        presets = QGridLayout()
        presets.setSpacing(4)
        for i, (text, value) in enumerate(PRESETS):
            b = chip(text, value == self.value, 108)
            b.clicked.connect(lambda _=False, v=value: self.pick(v))
            presets.addWidget(b, i // 2, i % 2)
        body.addLayout(presets)
        row = QHBoxLayout()
        row.setSpacing(4)
        days = self._days()
        self.day_chips = []
        for i, name in enumerate(DAY_SHORT):
            b = chip(name, i in days, 28)
            b.clicked.connect(lambda _=False, d=i: self._toggle(d))
            row.addWidget(b)
            self.day_chips.append(b)
        body.addLayout(row)

    def _toggle(self, day: int) -> None:
        days = self._days() ^ {day}
        if not days:
            return  # keep at least one day
        self.pick(format_weekdays(frozenset(days)), close=False)
        for i, b in enumerate(self.day_chips):
            _set_active(b, i in days)


class Wheel(QWidget):
    """A looping scroll column: wheel, drag, click a row or use the arrow keys."""

    ROW = 30
    VISIBLE = 5

    def __init__(self, labels: list[str], index: int):
        super().__init__()
        self.labels = labels
        self.offset = float(index)
        self.setFixedSize(60, self.ROW * self.VISIBLE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QVariantAnimation(self, duration=160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_offset)
        self._press: tuple[float, float] | None = None
        self._moved = False
        self._wheel_rest = 0

    def index(self) -> int:
        target = self._anim.endValue() if self._anim.state() == QVariantAnimation.State.Running else self.offset
        return round(target) % len(self.labels)

    def _set_offset(self, value) -> None:
        self.offset = float(value)
        self.update()

    def _scroll_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.offset)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def step(self, delta: int) -> None:
        base = self._anim.endValue() if self._anim.state() == QVariantAnimation.State.Running else self.offset
        self._scroll_to(round(base) + delta)

    def wheelEvent(self, event):
        self._wheel_rest += event.angleDelta().y()
        steps = int(self._wheel_rest / 120)
        if steps:
            self._wheel_rest -= steps * 120
            self.step(-steps)
        event.accept()

    def mousePressEvent(self, event):
        self._anim.stop()
        self._press = (event.position().y(), self.offset)
        self._moved = False
        self.setFocus()

    def mouseMoveEvent(self, event):
        if self._press:
            dy = event.position().y() - self._press[0]
            self._moved = self._moved or abs(dy) > 3
            self._set_offset(self._press[1] - dy / self.ROW)

    def mouseReleaseEvent(self, event):
        if not self._press:
            return
        if self._moved:
            self._scroll_to(round(self.offset))
        else:
            self.step(round((event.position().y() - self.height() / 2) / self.ROW))
        self._press = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Up:
            self.step(-1)
        elif event.key() == Qt.Key.Key_Down:
            self.step(1)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        band = QRectF(2, cy - self.ROW / 2, self.width() - 4, self.ROW)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color(t.INK, 22 if self.hasFocus() else 14))
        p.drawRoundedRect(band, 6, 6)
        base = math.floor(self.offset)
        frac = self.offset - base
        for k in range(-3, 4):
            y = cy + (k - frac) * self.ROW
            distance = abs(k - frac)
            centre = distance < 0.5
            p.setFont(t.font(t.MONO, 12 if centre else 11, QFont.Weight.Medium if centre else QFont.Weight.Normal))
            p.setPen(t.color(t.INK) if centre else t.color(t.MUTED, max(0, int(255 - 70 * distance))))
            p.drawText(QRectF(0, y - self.ROW / 2, self.width(), self.ROW), Qt.AlignmentFlag.AlignCenter,
                       self.labels[(base + k) % len(self.labels)])
        for top in (True, False):  # fade rows into the panel at both ends
            edge = QRectF(0, 0 if top else self.height() - self.ROW, self.width(), self.ROW)
            fade = QLinearGradient(0, edge.top(), 0, edge.bottom())
            fade.setColorAt(0 if top else 1, t.color(t.RAISED))
            fade.setColorAt(1 if top else 0, t.color(t.RAISED, 0))
            p.fillRect(edge, fade)
        p.end()


class TimeField(PickerField):
    """Opens two scrolling columns, hours and minutes, confirmed with "set"."""

    def display(self, value: time) -> str:
        return f"{value:%H:%M}"

    def fill(self, body: QVBoxLayout) -> None:
        self.hours = Wheel([f"{h:02d}" for h in range(24)], self.value.hour)
        self.minutes = Wheel([f"{m:02d}" for m in range(60)], self.value.minute)
        colon = QLabel(":")
        colon.setFont(t.font(t.MONO, 12, QFont.Weight.Medium))
        wheels = QHBoxLayout()
        wheels.setSpacing(2)
        wheels.addWidget(self.hours)
        wheels.addWidget(colon)
        wheels.addWidget(self.minutes)
        body.addLayout(wheels)
        cancel = QPushButton("cancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.popup.close)
        accept = QPushButton("set")
        accept.setProperty("kind", "solid")
        accept.setCursor(Qt.CursorShape.PointingHandCursor)
        accept.clicked.connect(lambda: self.pick(time(self.hours.index(), self.minutes.index())))
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        body.addLayout(buttons)
        self.hours.setFocus()


class NumberField(QFrame):
    """[−] value unit [+]: type any number, scroll, use arrow keys or hold − / +."""

    changed = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str, width: int):
        super().__init__()
        self.setProperty("role", "field")
        self.minimum, self.maximum = minimum, maximum
        self.value = value
        self.setFixedSize(width, 30)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(0)
        self.minus = self._stepper("−", -1)
        self.edit = QLineEdit()
        self.edit.setProperty("kind", "bare")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.edit.setValidator(QIntValidator(0, maximum, self))
        self.edit.setTextMargins(0, 0, 0, 0)
        self.edit.textChanged.connect(self._fit)
        self.edit.editingFinished.connect(self._commit)
        self.edit.installEventFilter(self)
        # "15 min" but "100%": a word unit gets a space, a symbol does not.
        unit_label = QLabel(unit if len(unit) == 1 else f" {unit}")
        unit_label.setProperty("role", "muted")
        self.plus = self._stepper("+", 1)
        row.addWidget(self.minus)
        row.addStretch(1)
        row.addWidget(self.edit)
        row.addWidget(unit_label)
        row.addStretch(1)
        row.addWidget(self.plus)
        self.set_value(value)

    def _stepper(self, text: str, direction: int) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("kind", "step")
        b.setFixedSize(24, 24)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setAutoRepeat(True)
        b.setAutoRepeatDelay(350)
        b.setAutoRepeatInterval(60)
        b.clicked.connect(lambda: self.bump(direction))
        return b

    def _fit(self, text: str) -> None:
        """Keep the number exactly as wide as its digits so "value unit" stays centred."""
        width = self.edit.fontMetrics().horizontalAdvance(text or "0")
        self.edit.setFixedWidth(width + 2)

    def editing(self) -> bool:
        return self.edit.hasFocus()

    def set_value(self, value: int) -> None:
        self.value = max(self.minimum, min(self.maximum, int(value)))
        self.edit.setText(str(self.value))
        self.minus.setEnabled(self.value > self.minimum)
        self.plus.setEnabled(self.value < self.maximum)

    def _emit_if_changed(self, old: int) -> None:
        if self.value != old:
            self.changed.emit(self.value)

    def bump(self, delta: int) -> None:
        old = self.value
        self.set_value(self.value + delta)
        self._emit_if_changed(old)

    def _commit(self) -> None:
        old = self.value
        text = self.edit.text().strip()
        self.set_value(int(text) if text else old)
        self._emit_if_changed(old)

    def wheelEvent(self, event):
        step = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if event.angleDelta().y():
            self.bump(step if event.angleDelta().y() > 0 else -step)
        event.accept()

    def eventFilter(self, obj, event):
        if obj is self.edit:
            if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                step = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
                self.bump(step if event.key() == Qt.Key.Key_Up else -step)
                return True
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                _set_active(self, event.type() == QEvent.Type.FocusIn)
        return super().eventFilter(obj, event)
