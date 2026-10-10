"""The spory window: a glanceable dashboard and a settings page."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spory import __version__, service_task
from spory.gui import theme as t
from spory.gui.model import Snapshot, build_snapshot
from spory.gui.pickers import DAY_NAMES, DaysField, NumberField, TimeField
from spory.gui.widgets import BigPercent, RunwayChart, StatusDot
from spory.hardware import is_admin, read_system_power_status
from spory.history import HistoryLog
from spory.schedule import OneTimeDeadline, WeeklyRule, format_weekdays, parse_weekdays
from spory.state import Config, Store

REFRESH_MS = 20_000
CHARGE_NOW_HOURS = 2
NOTICE_TITLE = "A limit stops charging. It does not drain."
NOTICE_BODY = (
    "spory can stop charging at any level, but it cannot make the battery go down "
    "while the charger is plugged in. If the battery is above your limit, it stays "
    "there until you use the laptop unplugged."
)
TONES = {"good": t.SAGE, "warn": t.AMBER, "bad": t.CORAL, "muted": t.MUTED}

# Layout grid: one spacing scale, symmetric margins.
COMPACT_WIDTH = 500  # below: smaller number, settings labels stack above controls
LARGE_WIDTH = 800  # from here: larger number
MARGINS = {"compact": (16, 12, 16, 16), "normal": (20, 12, 20, 16), "large": (24, 12, 24, 20)}
LABEL_COLUMN = 112
DAYS_W, TIME_W, TARGET_W = 110, 70, 100
RESIZE_EDGE = 6


def now_local() -> datetime:
    return datetime.now().astimezone()


def label(text: str = "", role: str | None = None, size: float = 10, weight=QFont.Weight.Normal) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setFont(t.font(t.MONO, size, weight))
    return w


def section_label(text: str) -> QLabel:
    w = label(text.upper(), "section", 8.5, QFont.Weight.Medium)
    font = w.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    w.setFont(font)
    return w


def button(text: str, kind: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def set_prop(widget: QWidget, name: str, value) -> None:
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def hbox(*items, spacing: int = 8, stretch: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    for item in items:
        row.addWidget(item)
    if stretch:
        row.addStretch(1)
    return row


class LimitSlider(QSlider):
    """Ignores the mouse wheel so scrolling past it never changes the battery limit."""

    def wheelEvent(self, event):
        event.ignore()


class TitleBar(QWidget):
    """The header doubles as the title bar: drag to move, double-click to maximize."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()


class Backdrop(QWidget):
    """Warm graphite with film grain and a faint bloom behind the battery level.

    Its outer few pixels resize the borderless window.
    """

    def __init__(self, parent=None, resizable: bool = True):
        super().__init__(parent)
        self.grain = t.grain_tile(strength=10)
        self.tint = t.SAGE
        self.bloom = QPointF(120, 110)
        self.resizable = resizable
        self.setMouseTracking(resizable)

    def set_tint(self, tint: str) -> None:
        if tint != self.tint:
            self.tint = tint
            self.update()

    def set_bloom(self, point: QPointF) -> None:
        if point != self.bloom:
            self.bloom = point
            self.update()

    def _edges(self, pos) -> Qt.Edge:
        edges = Qt.Edge(0)
        if not self.resizable or self.window().isMaximized():
            return edges
        if pos.x() < RESIZE_EDGE:
            edges |= Qt.Edge.LeftEdge
        if pos.x() > self.width() - RESIZE_EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() < RESIZE_EDGE:
            edges |= Qt.Edge.TopEdge
        if pos.y() > self.height() - RESIZE_EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event):
        e = self._edges(event.position().toPoint())
        if e in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif e in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif e & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif e & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        edges = self._edges(event.position().toPoint())
        if edges and event.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemResize(edges)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), t.color(t.INK_BG))
        bloom = QRadialGradient(self.bloom, 260)
        bloom.setColorAt(0, t.color(self.tint, 26))
        bloom.setColorAt(1, t.color(self.tint, 0))
        p.fillRect(self.rect(), bloom)
        p.drawTiledPixmap(self.rect(), self.grain)
        if not self.window().isMaximized():
            p.setPen(t.color(t.LINE))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()


class NoticeDialog(QDialog):
    """A themed, borderless one-time notice."""

    def __init__(self, parent: QWidget, title: str, body: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(360)
        backdrop = Backdrop(self, resizable=False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(backdrop)
        col = QVBoxLayout(backdrop)
        col.setContentsMargins(20, 20, 20, 20)
        col.setSpacing(8)
        heading = label(title, size=11, weight=QFont.Weight.Bold)
        heading.setWordWrap(True)
        col.addWidget(heading)
        text = label(body, "muted", 10)
        text.setWordWrap(True)
        col.addWidget(text)
        col.addSpacing(8)
        ok = button("ok", "solid")
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok)
        col.addLayout(row)

    def showEvent(self, event):
        super().showEvent(event)
        t.round_corners(self)


class DepartureRow(QWidget):
    """days | time | target | ×, in the same columns as the add form below it."""

    removed = Signal()

    def __init__(self, days: str, clock: str, target: str, muted: bool = False):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for text, width, role in ((days, DAYS_W, "muted"), (clock, TIME_W, "muted" if muted else None),
                                  (target, TARGET_W, None)):
            w = label(text, role, 10)
            w.setFixedWidth(width)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(w)
        remove = button("×", "ghost")
        remove.setFixedSize(24, 24)
        remove.setToolTip("remove")
        remove.clicked.connect(self.removed.emit)
        row.addWidget(remove)
        row.addStretch(1)


class MainWindow(QWidget):
    snapshot_changed = Signal(object)
    hidden_to_tray = Signal()
    update_requested = Signal()
    check_requested = Signal()

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.history = HistoryLog(store.history_path)
        self.snapshot: Snapshot | None = None
        self._first = True
        self._scale: str | None = None
        self.setWindowTitle("spory")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.resize(560, 420)
        self.setMinimumSize(QSize(420, 300))

        self.backdrop = Backdrop(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.backdrop)
        self.root = QVBoxLayout(self.backdrop)
        self.root.addWidget(self._header())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._dashboard())
        self.pages.addWidget(self._settings())
        self.root.addWidget(self.pages, 1)
        self._show_page(0)
        self._apply_breakpoints()

        self.timer = QTimer(self, interval=REFRESH_MS, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    # header -----------------------------------------------------------------
    def _header(self) -> QWidget:
        bar = TitleBar()
        bar.setFixedHeight(32)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(label("spory", size=12, weight=QFont.Weight.Bold))
        row.addStretch(1)
        self.update_pill = button("", "update")
        self.update_pill.hide()
        self.update_pill.clicked.connect(self.update_requested.emit)
        row.addWidget(self.update_pill)
        row.addSpacing(12)
        self.tabs = [button("dash", "tab"), button("settings", "tab")]
        for i, tab in enumerate(self.tabs):
            tab.clicked.connect(lambda _=False, i=i: self._show_page(i))
            row.addWidget(tab)
            row.addSpacing(12)
        row.addSpacing(4)
        for glyph, kind, tip, slot in (("–", "win", "minimize", self.showMinimized),
                                       ("×", "win-close", "hide to tray", self.close)):
            b = button(glyph, kind)
            b.setFixedSize(32, 28)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        return bar

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for i, tab in enumerate(self.tabs):
            set_prop(tab, "active", "true" if i == index else "false")

    # dashboard ----------------------------------------------------------------
    def _dashboard(self) -> QWidget:
        page = QWidget()
        self.dash = QVBoxLayout(page)
        self.dash.setContentsMargins(0, 0, 0, 0)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.big = BigPercent()
        hero.addWidget(self.big, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        hero.addStretch(1)
        self.facts = QWidget()
        facts = QVBoxLayout(self.facts)
        facts.setSpacing(8)
        self.state = label("", size=11, weight=QFont.Weight.Bold)
        facts.addWidget(self.state)
        rows = QGridLayout()
        rows.setHorizontalSpacing(12)
        rows.setVerticalSpacing(4)
        self.row_labels = []
        for i in range(3):
            key, value = label("", "key", 10), label("", size=10)
            rows.addWidget(key, i, 0)
            rows.addWidget(value, i, 1)
            self.row_labels.append((key, value))
        facts.addLayout(rows)
        hero.addWidget(self.facts, 0, Qt.AlignmentFlag.AlignBottom)
        self.dash.addLayout(hero)

        self.chart = RunwayChart()
        self.dash.addWidget(self.chart, 1)

        self.charge_now = button("charge now", "primary")
        self.charge_now.clicked.connect(self.toggle_charge_now)
        self.skip_tomorrow = button("skip tomorrow")
        self.skip_tomorrow.clicked.connect(self.toggle_skip_tomorrow)
        self.status_dot = StatusDot()
        actions = hbox(self.charge_now, self.skip_tomorrow)
        actions.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.dash.addLayout(actions)
        return page

    # settings -----------------------------------------------------------------
    def _settings(self) -> QWidget:
        # limit
        self.limit_slider = LimitSlider(Qt.Orientation.Horizontal)
        self.limit_slider.setRange(20, 100)
        self.limit_slider.setPageStep(5)
        self.limit_slider.setFixedWidth(200)
        self.limit_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.limit_value = label("", size=10)
        self.limit_slider.valueChanged.connect(lambda v: self.limit_value.setText(f"{v}%"))
        self.limit_slider.valueChanged.connect(lambda _: None if self.limit_slider.isSliderDown() else self._save_limit())
        self.limit_slider.sliderReleased.connect(self._save_limit)
        limit = QWidget()
        col = QVBoxLayout(limit)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addLayout(hbox(self.limit_slider, self.limit_value))
        col.addWidget(label("stops charging only; can't drain on AC", "muted", 9))

        # margin
        self.margin = NumberField(0, 240, 15, "min", 110)
        self.margin.changed.connect(lambda _: self._save_margin())
        margin = QWidget()
        margin.setLayout(hbox(self.margin))

        # departures: list and form share the same columns
        departures = QWidget()
        col = QVBoxLayout(departures)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.departure_list = QVBoxLayout()
        self.departure_list.setSpacing(4)
        col.addLayout(self.departure_list)
        self.repeat = DaysField(DAYS_W, "mon-fri")
        self.when = TimeField(TIME_W, time(9, 30))
        self.target = NumberField(20, 100, 100, "%", TARGET_W)
        add = button("add", "solid")
        add.clicked.connect(self._add_departure)
        col.addLayout(hbox(self.repeat, self.when, self.target, add))

        # service and version
        self.service_text = label("", "muted", 10)
        self.service_button = button("")
        self.service_button.clicked.connect(self._toggle_service)
        service = QWidget()
        service.setLayout(hbox(self.service_text, self.service_button, spacing=12))
        self.version_text = label(f"spory {__version__}", "muted", 10)
        self.version_button = button("check")
        self.version_button.clicked.connect(self._version_clicked)
        version = QWidget()
        version.setLayout(hbox(self.version_text, self.version_button, spacing=12))

        self.sections = [
            ("limit", limit), ("margin", margin), None,
            ("departures", departures), None,
            ("service", service), ("version", version),
        ]
        self.section_labels = {name: section_label(name) for name, _ in filter(None, self.sections)}
        self.rules = [self._rule() for section in self.sections if section is None]
        self.settings_grid = QGridLayout()
        self.settings_grid.setContentsMargins(0, 0, 8, 0)
        self.settings_grid.setHorizontalSpacing(12)
        self.settings_grid.setVerticalSpacing(12)
        self.settings_grid.setColumnMinimumWidth(0, LABEL_COLUMN)
        body = QWidget()
        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addLayout(self.settings_grid)
        wrap.addStretch(1)
        self._stacked: bool | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _place_sections(self, stacked: bool) -> None:
        """Labels left of controls, or above them when the window is narrow."""
        if stacked == self._stacked:
            return
        self._stacked = stacked
        grid = self.settings_grid
        while grid.count():
            grid.takeAt(0)
        self.settings_grid.setColumnMinimumWidth(0, 0 if stacked else LABEL_COLUMN)
        row = 0
        rules = iter(self.rules)
        for section in self.sections:
            if section is None:
                grid.addWidget(next(rules), row, 0, 1, 2)
                row += 1
                continue
            name, content = section
            title = self.section_labels[name]
            if stacked:
                grid.addWidget(title, row, 0, 1, 2)
                grid.addWidget(content, row + 1, 0, 1, 2)
                row += 2
            else:
                title.setContentsMargins(0, 7, 0, 0)  # centre on the first 28px control row
                grid.addWidget(title, row, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(content, row, 1)
                row += 1
            if stacked:
                title.setContentsMargins(0, 0, 0, 0)

    @staticmethod
    def _rule() -> QWidget:
        """A divider with 24px above and 16px below (including grid spacing)."""
        line = QFrame()
        line.setProperty("role", "rule")
        line.setFixedHeight(1)
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 12, 0, 4)
        box.addWidget(line)
        return holder

    # data -------------------------------------------------------------------
    def refresh(self) -> None:
        config = self.store.load()
        now = now_local()
        try:
            status = read_system_power_status()
        except OSError:
            self.state.setText("NO BATTERY")
            return
        samples = self.history.read()
        snap = build_snapshot(config, status, now, [(s.at, s.percent) for s in samples], self.store.read_status())
        self.snapshot = snap

        tint = t.AMBER if snap.charging_now else t.SAGE
        self.big.set_value(status.percent, tint)
        self.backdrop.set_tint(tint)
        self.state.setText(f"● {snap.state}  {snap.decision.cap:g}%")
        self.state.setStyleSheet(f"color: {TONES[snap.tone]};")
        for i, (key, value) in enumerate(self.row_labels):
            k, v = snap.rows[i] if i < len(snap.rows) else ("", "")
            key.setText(k)
            value.setText(v)
            key.setVisible(bool(k))
            value.setVisible(bool(k))
        self.chart.set_data(snap.runway, animate=self._first)
        self._first = False
        service = snap.service
        self.status_dot.set_state(service.label, TONES[service.tone], service.detail)

        self._sync_controls(config, now)
        self._fill_departures(config)
        installed = service.running or service_task.is_installed()
        self.service_text.setText(f"{service.label} · {service.detail}" if service.running else service.label)
        self.service_text.setToolTip(service.detail)
        self.service_button.setText("remove" if installed else "install")
        set_prop(self.service_button, "kind", None if installed else "solid")
        QTimer.singleShot(0, self._place_bloom)
        self.snapshot_changed.emit(snap)

    def _place_bloom(self) -> None:
        if self.big.isVisible():
            self.backdrop.set_bloom(QPointF(self.big.mapTo(self.backdrop, self.big.rect().center())))

    def _sync_controls(self, config: Config, now: datetime) -> None:
        self.limit_slider.blockSignals(True)
        self.limit_slider.setValue(round(config.normal_cap))
        self.limit_slider.blockSignals(False)
        self.limit_value.setText(f"{config.normal_cap:g}%")
        if not self.margin.editing():
            self.margin.set_value(round(config.safety_margin_minutes))
        active = bool(config.charge_now_until and now < config.charge_now_until)
        self.charge_now.setText("stop charging" if active else "charge now")
        set_prop(self.charge_now, "kind", None if active else "primary")
        skipped = now.date() + timedelta(days=1) in config.schedule.skip_dates
        self.skip_tomorrow.setText("unskip tomorrow" if skipped else "skip tomorrow")

    def _fill_departures(self, config: Config) -> None:
        while self.departure_list.count():
            item = self.departure_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, r in enumerate(config.schedule.weekly):
            days = format_weekdays(r.weekdays)
            row = DepartureRow(DAY_NAMES.get(days, days), f"{r.at:%H:%M}", f"→ {r.target_percent:g}%")
            row.removed.connect(lambda i=i: self._remove("weekly", i))
            self.departure_list.addWidget(row)
        for once in sorted(config.schedule.one_time, key=lambda o: o.at):
            at = once.at.astimezone()
            row = DepartureRow(f"{at:%a %d %b}".lower(), f"{at:%H:%M}", f"→ {once.target_percent:g}%")
            row.removed.connect(lambda o=once: self._remove("once", o))
            self.departure_list.addWidget(row)
        for day in sorted(config.schedule.skip_dates):
            row = DepartureRow(f"skip {day:%a %d}".lower(), "", "", muted=True)
            row.removed.connect(lambda d=day: self._remove("skip", d))
            self.departure_list.addWidget(row)
        if not self.departure_list.count():
            self.departure_list.addWidget(label("none yet", "key", 10))

    # edits ------------------------------------------------------------------
    def _edit(self, change) -> None:
        config = self.store.load()
        change(config)
        self.store.save(config)
        self.refresh()

    def _save_limit(self) -> None:
        value = float(self.limit_slider.value())
        if value != self.store.load().normal_cap:
            self._edit(lambda c: setattr(c, "normal_cap", value))

    def _save_margin(self) -> None:
        value = float(self.margin.value)
        if value != self.store.load().safety_margin_minutes:
            self._edit(lambda c: setattr(c, "safety_margin_minutes", value))

    def _add_departure(self) -> None:
        at = self.when.value
        target = float(self.target.value)
        repeat = self.repeat.value
        if repeat == "once":
            now = now_local()
            when = datetime.combine(now.date(), at).astimezone()
            if when <= now:
                when = datetime.combine(now.date() + timedelta(days=1), at).astimezone()
            self._edit(lambda c: c.schedule.one_time.append(OneTimeDeadline(when, target)))
        else:
            self._edit(lambda c: c.schedule.weekly.append(WeeklyRule(parse_weekdays(repeat), at, target)))

    def _remove(self, kind: str, key) -> None:
        def change(c: Config):
            if kind == "weekly":
                c.schedule.weekly.pop(key)
            elif kind == "once":
                c.schedule.one_time = [o for o in c.schedule.one_time if o != key]
            else:
                c.schedule.skip_dates.discard(key)

        self._edit(change)

    def toggle_charge_now(self) -> None:
        now = now_local()

        def change(c: Config):
            active = c.charge_now_until and now < c.charge_now_until
            c.charge_now_until = None if active else now + timedelta(hours=CHARGE_NOW_HOURS)

        self._edit(change)

    def toggle_skip_tomorrow(self) -> None:
        tomorrow: date = now_local().date() + timedelta(days=1)

        def change(c: Config):
            if tomorrow in c.schedule.skip_dates:
                c.schedule.skip_dates.discard(tomorrow)
            else:
                c.schedule.skip_dates.add(tomorrow)

        self._edit(change)

    def _toggle_service(self) -> None:
        action = "uninstall" if self.service_button.text() == "remove" else "install"
        if is_admin():
            try:
                service_task.register() if action == "install" else service_task.unregister()
            except RuntimeError as exc:
                QMessageBox.warning(self, "spory", str(exc))
        elif service_task.run_elevated("service", action, wait=False) is None:
            QMessageBox.information(self, "spory", "Administrator approval is needed to change the service.")
        QTimer.singleShot(4000, self.refresh)

    # updates ------------------------------------------------------------------
    def show_update(self, version: str | None, note: str = "") -> None:
        """version: newer release available, None: up to date or unknown."""
        self._update_version = version
        for b in (self.update_pill, self.version_button):
            b.setEnabled(True)
        if version:
            self.update_pill.setText(f"update {version}")
            self.update_pill.show()
            self.version_text.setText(f"spory {__version__} · {version} available")
            self.version_button.setText("update")
            set_prop(self.version_button, "kind", "solid")
        else:
            self.update_pill.hide()
            self.version_text.setText(f"spory {__version__}" + (f" · {note}" if note else ""))
            self.version_button.setText("check")
            set_prop(self.version_button, "kind", None)

    def set_update_busy(self, text: str) -> None:
        for b in (self.update_pill, self.version_button):
            b.setEnabled(False)
        self.update_pill.setText(text)
        self.version_button.setText(text)

    def _version_clicked(self) -> None:
        if getattr(self, "_update_version", None):
            self.update_requested.emit()
        else:
            self.version_button.setText("checking…")
            self.check_requested.emit()

    # window -----------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_breakpoints()
        QTimer.singleShot(0, self._place_bloom)

    def _apply_breakpoints(self) -> None:
        """Responsive layout: number size, margins, spacing and settings stacking."""
        width = self.width()
        scale = "compact" if width < COMPACT_WIDTH else "large" if width >= LARGE_WIDTH else "normal"
        self._place_sections(width < COMPACT_WIDTH)
        if scale == self._scale:
            return
        self._scale = scale
        gap = 12 if scale == "compact" else 16
        self.root.setContentsMargins(*MARGINS[scale])
        self.root.setSpacing(gap)
        self.dash.setSpacing(gap)
        self.big.set_scale(scale)
        # Put the last fact's baseline on the number's baseline.
        inset = self.big.descent - QFontMetricsF(t.font(t.MONO, 10)).descent()
        self.facts.layout().setContentsMargins(0, 0, 0, max(0, round(inset)))

    def showEvent(self, event):
        super().showEvent(event)
        t.round_corners(self)
        if not self.store.load().notice_seen:
            QTimer.singleShot(400, self._show_notice)

    def _show_notice(self) -> None:
        if self.store.load().notice_seen:
            return
        NoticeDialog(self, NOTICE_TITLE, NOTICE_BODY).exec()
        self._edit(lambda c: setattr(c, "notice_seen", True))

    def closeEvent(self, event):
        # Closing hides to the tray; quit from the tray menu.
        event.ignore()
        self.hide()
        self.hidden_to_tray.emit()
