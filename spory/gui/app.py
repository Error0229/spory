"""Entry point: `spory gui` or `spory-gui`. Runs in the tray; the window opens on demand."""

from __future__ import annotations

import getpass
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from spory import updater

from spory.gui import theme as t
from spory.gui.model import Snapshot
from spory.gui.widgets import tray_icon
from spory.gui.window import MainWindow
from spory.state import Store


class Tray(QSystemTrayIcon):
    def __init__(self, window: MainWindow, app: QApplication):
        super().__init__(tray_icon(50, False, True), app)
        self.window = window
        self.hint_shown = False
        menu = QMenu()
        self.summary = QAction("", menu, enabled=False)
        menu.addAction(self.summary)
        menu.addSeparator()
        menu.addAction("open", self.open)
        self.charge_action = menu.addAction("charge now", window.toggle_charge_now)
        self.skip_action = menu.addAction("skip tomorrow", window.toggle_skip_tomorrow)
        menu.addSeparator()
        menu.addAction("quit", app.quit)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        window.snapshot_changed.connect(self.update_from)
        window.hidden_to_tray.connect(self._hidden)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open()

    def open(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _hidden(self):
        if not self.hint_shown:
            self.hint_shown = True
            self.showMessage("spory", "Still running in the tray.", QSystemTrayIcon.MessageIcon.NoIcon, 2500)

    def update_from(self, snap: Snapshot):
        s = snap.status
        self.setIcon(tray_icon(s.percent, snap.charging_now and s.plugged_in, s.plugged_in))
        line = f"{s.percent:g}% · {snap.state.lower()}"
        self.setToolTip(f"spory · {line}")
        self.summary.setText(line)
        self.charge_action.setText(self.window.charge_now.text())
        self.skip_action.setText(self.window.skip_tomorrow.text())


UPDATE_CHECK_MS = 12 * 60 * 60 * 1000
INSTANCE_NAME = f"spory-gui-{getpass.getuser()}"


class Updates(QObject):
    """Checks GitHub Releases off the UI thread and runs the installer on request."""

    checked = Signal(object, str)  # newer release or None, note
    downloaded = Signal(object)  # Path, or an error message

    def __init__(self, window: MainWindow, app: QApplication):
        super().__init__(app)
        self.window = window
        self.app = app
        self.release = None
        self.checked.connect(self._on_checked)
        self.downloaded.connect(self._on_downloaded)
        window.check_requested.connect(self.check)
        window.update_requested.connect(self.install)
        self.timer = QTimer(self, interval=UPDATE_CHECK_MS, timeout=self.check)
        self.timer.start()
        QTimer.singleShot(5000, self.check)

    def check(self) -> None:
        def work():
            latest = updater.latest_release()
            if latest is None:
                self.checked.emit(None, "update check unavailable")
            elif updater.is_newer(latest.version):
                self.checked.emit(latest, "")
            else:
                self.checked.emit(None, "up to date")

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, release, note: str) -> None:
        self.release = release
        self.window.show_update(release.version if release else None, note)

    def install(self) -> None:
        if not self.release:
            return
        self.window.set_update_busy("downloading…")
        release = self.release

        def work():
            try:
                self.downloaded.emit(updater.download(release))
            except updater.UpdateError as exc:
                self.downloaded.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_downloaded(self, result) -> None:
        if isinstance(result, str):
            QMessageBox.warning(self.window, "spory", result)
            self.window.show_update(self.release.version)
            return
        try:
            updater.launch_installer(result)
        except OSError:  # UAC declined
            self.window.show_update(self.release.version)
            return
        # The installer replaces these files and relaunches spory afterwards.
        QTimer.singleShot(1500, self.app.quit)


def already_running() -> bool:
    """Ask a running instance to show its window; True if one answered."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def listen_for_others(tray: Tray, app: QApplication) -> QLocalServer:
    QLocalServer.removeServer(INSTANCE_NAME)  # clear a stale socket after a crash
    server = QLocalServer(app)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), tray.open()))
    server.listen(INSTANCE_NAME)
    return server


def main(argv: list[str] | None = None) -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("spory")
    app.setQuitOnLastWindowClosed(False)
    t.load_fonts()
    app.setStyle("Fusion")
    app.setFont(t.font(t.MONO, 10))
    app.setStyleSheet(t.STYLESHEET)
    if already_running():
        return 0

    window = MainWindow(Store())
    tray = Tray(window, app)
    if window.snapshot:
        tray.update_from(window.snapshot)
    app.setWindowIcon(tray_icon(80, False, True))
    tray.show()
    app._server = listen_for_others(tray, app)
    app._updates = Updates(window, app)
    if "--tray" not in app.arguments():
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
