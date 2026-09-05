"""Entry point. Builds the QApplication, the controller, the window and
the tray icon, optionally starts the backend, and runs."""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_NAME, config, mods
from .controller import Controller
from .ui.main_window import MainWindow, make_icon
from .ui.settings_dialog import SettingsWindow


class Application:
    def __init__(self, argv):
        os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")
        self.qt = QApplication(argv)
        self.qt.setApplicationName(APP_NAME)
        self.qt.setDesktopFileName("genesis-desktop")
        self.qt.setQuitOnLastWindowClosed(False)
        config.ensure_dirs()
        self.backend_proc = None
        self.controller = Controller()
        self.client = self.controller.client
        self.window = MainWindow(self.controller, lambda parent: SettingsWindow(self.controller, parent))
        self.tray = None
        self._build_tray()
        self.controller.state_changed.connect(self._tray_state)
        self.controller.error.connect(self._tray_error)
        signal.signal(signal.SIGINT, lambda *a: self.quit())
        # let python handle SIGINT while the Qt loop runs
        self._sig_timer = QTimer()
        self._sig_timer.timeout.connect(lambda: None)
        self._sig_timer.start(300)

    # ------------------------------------------------------------------
    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(self.window.accent, "offline"), self.qt)
        menu = QMenu()
        show = QAction("Show Genesis", menu)
        show.triggered.connect(self._show)
        self.tray_mute = QAction("Mute", menu, checkable=True)
        self.tray_mute.toggled.connect(self.controller.set_muted)
        talk = QAction("Push to talk (hold Space in window)", menu)
        talk.triggered.connect(self._show)
        settings = QAction("Settings…", menu)
        settings.triggered.connect(lambda: self.window.open_settings())
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self.quit)
        for a in (show, self.tray_mute, talk):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(settings)
        menu.addAction(quit_)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._toggle() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Genesis")
        self.tray.show()
        self.window.tray_enabled = True

    def _tray_state(self, s):
        if self.tray:
            self.tray.setIcon(make_icon(self.window.accent, s))
            self.tray.setToolTip(f"Genesis — {self.controller.persona.title()} — {s}")
            self.tray_mute.blockSignals(True)
            self.tray_mute.setChecked(self.controller.muted)
            self.tray_mute.blockSignals(False)

    def _tray_error(self, msg):
        if self.tray and not self.window.isVisible():
            self.tray.showMessage("Genesis", msg, QSystemTrayIcon.Warning, 4000)

    def _show(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _toggle(self):
        if self.window.isVisible() and not self.window.isMinimized():
            self.window.hide()
        else:
            self._show()

    # ------------------------------------------------------------------
    def maybe_start_backend(self):
        if not config.get("autostart_backend"):
            return
        try:
            self.client.health()
            return                       # already running
        except Exception:
            pass
        cwd = config.get("backend_dir") or None
        cmd = config.get("backend_command")
        if not cmd:
            return
        try:
            self.backend_proc = subprocess.Popen(
                shlex.split(cmd), cwd=cwd or None,
                stdout=open(config.LOG_DIR / "backend.log", "ab"),
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            self.controller.status.emit("backend", "starting backend…")
            QTimer.singleShot(4000, self.controller.connect)
            QTimer.singleShot(12000, self.controller.connect)
        except Exception as e:
            self.controller.error.emit(f"could not start backend: {e}")

    def run(self):
        self.maybe_start_backend()
        if not config.get("start_in_tray") or not self.tray:
            self.window.show()
        self.controller.start()
        mods.run("startup", self)
        return self.qt.exec()

    def quit(self):
        self.window._quitting = True
        self.controller.shutdown()
        if self.backend_proc and self.backend_proc.poll() is None:
            try:
                self.backend_proc.terminate()
            except Exception:
                pass
        self.qt.quit()


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="genesis-desktop", description="Voice client for Genesis")
    ap.add_argument("--backend", help="backend URL, overrides the saved setting for this run")
    ap.add_argument("--persona", help="start with this persona")
    ap.add_argument("--doctor", action="store_true", help="print what is installed and missing, then exit")
    ap.add_argument("--tray", action="store_true", help="start hidden in the tray")
    args = ap.parse_args()
    if args.backend:
        os.environ["GENESIS_DESKTOP_BACKEND_URL"] = args.backend
    if args.persona:
        os.environ["GENESIS_DESKTOP_PERSONA"] = args.persona
    if args.tray:
        os.environ["GENESIS_DESKTOP_START_IN_TRAY"] = "1"
    if args.doctor:
        from . import doctor, tools
        tools.load_builtins()
        mods.load_enabled()
        print(doctor.report())
        return 0
    app = Application(sys.argv)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
