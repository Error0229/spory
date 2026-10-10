"""Painted widgets: the charge runway, the big percentage, the status dot and the tray glyph."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import (
    QBrush,
    QRegion,
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from spory.gui import theme as t
from spory.gui.model import Runway

PAST = timedelta(hours=3)
TAIL = timedelta(minutes=20)
NO_DEADLINE_AHEAD = timedelta(hours=6)
# A flat stretch longer than this between "now" and the charge window is
# collapsed into a short break, so the window gets the width it deserves.
COLLAPSE_AFTER = timedelta(hours=3)
BREAK_PX = 16
LABEL_GAP_PX = 40


class RunwayChart(QWidget):
    """Battery level from 3 hours ago to the next departure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: Runway | None = None
        self.reveal = 0.0
        self.pulse = 0.0
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._reveal_anim = QVariantAnimation(self, duration=1300, startValue=0.0, endValue=1.0)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reveal_anim.valueChanged.connect(self._set_reveal)
        self._pulse_anim = QVariantAnimation(self, duration=2600, startValue=0.0, endValue=1.0, loopCount=-1)
        self._pulse_anim.valueChanged.connect(self._set_pulse)
        self._pulse_anim.start()

    def _set_reveal(self, value):
        self.reveal = value
        self.update()

    def _set_pulse(self, value):
        self.pulse = value
        self.update()

    def set_data(self, data: Runway, animate: bool = False) -> None:
        self.data = data
        if animate:
            self._reveal_anim.stop()
            self._reveal_anim.start()
        elif self._reveal_anim.state() != QVariantAnimation.State.Running:
            self.reveal = 1.0
        self.update()

    # geometry -------------------------------------------------------------
    def _span(self) -> tuple[datetime, datetime, tuple[datetime, datetime] | None]:
        d = self.data
        start = d.now - PAST
        end = d.deadline + TAIL if d.deadline else d.now + NO_DEADLINE_AHEAD
        gap = None
        if d.deadline and d.window_start and d.window_start > d.now:
            a, b = d.now + timedelta(hours=1), d.window_start - timedelta(hours=1)
            if b - a > COLLAPSE_AFTER:
                gap = (a, b)
        return start, end, gap

    def _plot(self) -> QRectF:
        return QRectF(0, 20, self.width(), self.height() - 20 - 18)

    def _x(self, at: datetime) -> float:
        start, end, gap = self._span()
        plot = self._plot()
        at = min(max(at, start), end)
        if not gap:
            return plot.left() + plot.width() * (at - start) / (end - start)
        a, b = gap
        scale = (plot.width() - BREAK_PX) / ((a - start) + (end - b)).total_seconds()
        if at <= a:
            return plot.left() + (at - start).total_seconds() * scale
        x_a = plot.left() + (a - start).total_seconds() * scale
        if at < b:
            return x_a + BREAK_PX * (at - a) / (b - a)
        return x_a + BREAK_PX + (at - b).total_seconds() * scale

    def _y(self, percent: float) -> float:
        plot = self._plot()
        return plot.bottom() - plot.height() * percent / 100

    # painting -------------------------------------------------------------
    def paintEvent(self, event):
        if not self.data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self.data
        plot = self._plot()
        now_x = self._x(d.now)

        gap = self._span()[2]
        if gap:
            # Lines stop at the break; the "≈" stands in for the hidden hours.
            x = self._x(gap[0])
            p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(int(x), 0, BREAK_PX, self.height())))
        p.setPen(QPen(t.color(t.LINE), 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        if d.window_start and d.deadline:
            x0, x1 = max(self._x(d.window_start), plot.left()), self._x(d.deadline)
            band = QLinearGradient(0, plot.top(), 0, plot.bottom())
            band.setColorAt(0, t.color(t.AMBER, 34))
            band.setColorAt(1, t.color(t.AMBER, 4))
            p.fillRect(QRectF(x0, plot.top(), x1 - x0, plot.height()), band)

        # the normal limit: where the battery rests
        y_cap = self._y(d.normal_cap)
        p.setPen(QPen(t.color(t.SAGE, 150), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(plot.left(), y_cap), QPointF(plot.right(), y_cap))
        p.setFont(t.font(t.MONO, 8))
        p.setPen(t.color(t.SAGE))
        p.drawText(QPointF(plot.left() + 2, y_cap + 13), f"{d.normal_cap:g}")

        self._paint_past(p, plot, now_x)
        self._paint_future(p, plot, now_x)
        p.setClipping(False)
        self._paint_break(p)
        self._paint_deadline(p, plot)
        self._paint_now(p, plot, now_x)
        self._paint_time_labels(p, plot, now_x)
        p.end()

    def _path(self, points: list[tuple[datetime, float]]) -> QPainterPath:
        path = QPainterPath()
        for i, (at, pct) in enumerate(points):
            pt = QPointF(self._x(at), self._y(pct))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        return path

    def _paint_past(self, p: QPainter, plot: QRectF, now_x: float) -> None:
        d = self.data
        start = d.now - PAST
        points = [(at, pct) for at, pct in d.past if at >= start] + [(d.now, d.percent)]
        if len(points) < 2:
            return
        line = self._path(points)
        area = QPainterPath(line)
        area.lineTo(QPointF(now_x, plot.bottom()))
        area.lineTo(QPointF(self._x(points[0][0]), plot.bottom()))
        area.closeSubpath()
        fill = QLinearGradient(0, plot.top(), 0, plot.bottom())
        fill.setColorAt(0, t.color(t.INK, 22))
        fill.setColorAt(1, t.color(t.INK, 0))
        p.fillPath(area, fill)
        p.setPen(QPen(t.color(t.MUTED), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)

    def _paint_future(self, p: QPainter, plot: QRectF, now_x: float) -> None:
        d = self.data
        if not d.future:
            return
        p.save()
        reveal_x = now_x + (plot.right() - now_x) * self.reveal
        p.setClipRect(QRectF(now_x, 0, reveal_x - now_x, self.height()))
        points = [(d.now, d.percent, d.future[0][2])] + d.future
        for i in range(1, len(points)):
            (a_at, a_pct, _), (b_at, b_pct, charging) = points[i - 1], points[i]
            if charging:
                xa, xb = self._x(a_at), self._x(b_at)
                poly = QPainterPath(QPointF(xa, self._y(a_pct)))
                poly.lineTo(QPointF(xb, self._y(b_pct)))
                poly.lineTo(QPointF(xb, plot.bottom()))
                poly.lineTo(QPointF(xa, plot.bottom()))
                poly.closeSubpath()
                glow = QLinearGradient(0, plot.top(), 0, plot.bottom())
                glow.setColorAt(0, t.color(t.AMBER, 70))
                glow.setColorAt(1, t.color(t.AMBER, 0))
                p.fillPath(poly, glow)
        for i in range(1, len(points)):
            (a_at, a_pct, _), (b_at, b_pct, charging) = points[i - 1], points[i]
            if charging:
                pen = QPen(t.color(t.AMBER), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            else:
                pen = QPen(t.color(t.INK, 150), 1.4, Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.RoundCap)
                pen.setDashPattern([1.5, 3.5])
            p.setPen(pen)
            p.drawLine(QPointF(self._x(a_at), self._y(a_pct)), QPointF(self._x(b_at), self._y(b_pct)))
        p.restore()

    def _paint_break(self, p: QPainter) -> None:
        gap = self._span()[2]
        if not gap:
            return
        x = self._x(gap[0])
        y = self._y(self.data.normal_cap)
        p.setFont(t.font(t.MONO, 10))
        p.setPen(t.color(t.MUTED))
        p.drawText(QRectF(x - 4, y - 10, BREAK_PX + 8, 20), Qt.AlignmentFlag.AlignCenter, "≈")

    def _paint_deadline(self, p: QPainter, plot: QRectF) -> None:
        d = self.data
        if not d.deadline:
            return
        x = self._x(d.deadline)
        p.setPen(QPen(t.color(t.CORAL), 1.2))
        p.drawLine(QPointF(x, plot.top() - 14), QPointF(x, plot.bottom()))
        p.setFont(t.font(t.MONO, 8.5, QFont.Weight.Medium))
        label = f"{d.deadline:%H:%M}" if d.deadline.date() == d.now.date() else f"{d.deadline:%a %H:%M}".lower()
        width = QFontMetricsF(p.font()).horizontalAdvance(label)
        left = x - width - 6 if x + 6 + width > self.width() else x + 6
        p.setPen(t.color(t.CORAL))
        p.drawText(QPointF(left, plot.top() - 6), label)
        if d.deadline_target is not None:
            y = self._y(d.deadline_target)
            diamond = QPainterPath()
            diamond.moveTo(x, y - 5)
            diamond.lineTo(x + 5, y)
            diamond.lineTo(x, y + 5)
            diamond.lineTo(x - 5, y)
            diamond.closeSubpath()
            p.fillPath(diamond, t.color(t.CORAL))

    def _paint_now(self, p: QPainter, plot: QRectF, now_x: float) -> None:
        d = self.data
        p.setPen(QPen(t.color(t.INK, 60), 1))
        p.drawLine(QPointF(now_x, plot.top()), QPointF(now_x, plot.bottom()))
        center = QPointF(now_x, self._y(d.percent))
        radius = 5 + 13 * self.pulse
        halo = QRadialGradient(center, radius)
        halo.setColorAt(0, t.color(t.INK, int(90 * (1 - self.pulse))))
        halo.setColorAt(1, t.color(t.INK, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(center, radius, radius)
        p.setBrush(t.color(t.INK))
        p.drawEllipse(center, 3.6, 3.6)

    def _paint_time_labels(self, p: QPainter, plot: QRectF, now_x: float) -> None:
        """Only the moments that matter: now, the charge start and midnight."""
        d = self.data
        start, end, gap = self._span()
        labels: list[tuple[float, str, str]] = [(now_x, "now", t.INK)]
        if d.window_start and d.deadline and d.window_start > d.now:
            labels.append((self._x(d.window_start), f"{d.window_start:%H:%M}", t.AMBER))
        midnight = (d.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        if start < midnight < end and not (gap and gap[0] < midnight < gap[1]):
            labels.append((self._x(midnight), f"{midnight:%a}".lower(), t.MUTED))
        avoid = [self._x(d.deadline)] if d.deadline else []
        p.setFont(t.font(t.MONO, 8))
        metrics = QFontMetricsF(p.font())
        placed: list[float] = []
        for x, text, colour in labels:
            if any(abs(x - other) < LABEL_GAP_PX for other in placed + avoid):
                continue
            width = metrics.horizontalAdvance(text)
            left = min(max(x - width / 2, 0), self.width() - width)
            p.setPen(t.color(colour))
            p.drawText(QPointF(left, self.height() - 4), text)
            placed.append(x)


class BigPercent(QWidget):
    """The battery level in large light mono, counting up on change.

    Sized to its text; the baseline sits at the bottom of the font's ascent so
    neighbours can align to it through `descent`.
    """

    SCALES = {"compact": (48, 16), "normal": (64, 20), "large": (80, 24)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.tint = t.SAGE  # color of the % sign: amber while charging, sage while holding
        self._anim = QVariantAnimation(self, duration=1100)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._step)
        self.set_scale("normal")

    def set_scale(self, name: str) -> None:
        number_pt, sign_pt = self.SCALES[name]
        self.number_font = t.font(t.MONO, number_pt, QFont.Weight.Light)
        self.sign_font = t.font(t.MONO, sign_pt, QFont.Weight.Light)
        metrics = QFontMetricsF(self.number_font)
        self.ascent = metrics.ascent()
        self.descent = metrics.descent()
        width = metrics.horizontalAdvance("100") + 4 + QFontMetricsF(self.sign_font).horizontalAdvance("%")
        self.setFixedSize(QSize(int(width) + 2, int(self.ascent + self.descent)))
        self.update()

    def _step(self, value):
        self.value = float(value)
        self.update()

    def set_value(self, value: float, tint: str) -> None:
        self.tint = tint
        if round(value) == round(self.value) and self._anim.state() != QVariantAnimation.State.Running:
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(float(value))
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        text = f"{round(self.value)}"
        p.setFont(self.number_font)
        p.setPen(t.color(t.INK))
        p.drawText(QPointF(0, self.ascent), text)
        p.setFont(self.sign_font)
        p.setPen(t.color(self.tint))
        p.drawText(QPointF(QFontMetricsF(self.number_font).horizontalAdvance(text) + 4, self.ascent), "%")
        p.end()


class StatusDot(QWidget):
    """Service health: a small colored dot and a word."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.dot = t.FAINT
        self.font_ = t.font(t.MONO, 9)
        self.setFixedHeight(20)

    def set_state(self, text: str, dot: str, tooltip: str = "") -> None:
        self.text, self.dot = text, dot
        self.setToolTip(tooltip)
        self.setFixedWidth(int(QFontMetricsF(self.font_).horizontalAdvance(text)) + 16)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color(self.dot))
        p.drawEllipse(QPointF(3, self.height() / 2), 3, 3)
        p.setFont(self.font_)
        p.setPen(t.color(t.MUTED))
        p.drawText(QRectF(14, 0, self.width() - 14, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text)
        p.end()


TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)


def _battery_glyph(size: int, percent: float, fill_color: str) -> QPixmap:
    """The battery at one pixel size, full icon width, every edge on a whole pixel."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    stroke = max(1, round(size / 12))
    nub_w = max(2, round(size / 10))
    height = round(size * 0.62)
    top = (size - height) // 2
    width = size - nub_w - 1
    body = QRectF(stroke / 2, top + stroke / 2, width - stroke, height - stroke)  # pen centred on the edge
    radius = max(1.5, size / 9)
    p.setPen(QPen(QColor(t.INK), stroke))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body, radius, radius)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(t.INK))
    nub_h = max(3, round(height * 0.42))
    p.drawRoundedRect(QRectF(width + 1, (size - nub_h) // 2, nub_w, nub_h), 1, 1)
    inset = stroke + max(1, size // 16)
    inner_w = width - 2 * inset
    level_w = max(1, round(inner_w * max(0.08, min(percent, 100) / 100)))
    level = QRectF(inset, top + inset, level_w, height - 2 * inset)
    p.setBrush(QColor(fill_color))
    p.drawRoundedRect(level, max(1.0, radius - inset), max(1.0, radius - inset))
    p.end()
    return pix


def tray_icon(percent: float, charging: bool, plugged: bool) -> QIcon:
    """A battery glyph filled to the current level, drawn natively at each tray size."""
    colour = t.AMBER if charging else t.SAGE if plugged else t.INK
    icon = QIcon()
    for size in TRAY_SIZES:
        icon.addPixmap(_battery_glyph(size, percent, colour))
    return icon
