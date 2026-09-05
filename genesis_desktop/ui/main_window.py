"""The main window: visualizer in the middle, status strip below, panels
on the sides that are hidden unless you want them."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QDockWidget, QLabel, QMainWindow, QToolBar,
                               QToolButton, QVBoxLayout, QWidget, QComboBox, QSizePolicy)

from .. import config
from . import theme
from .panels import ActivityPanel, ApprovalBar, ChatPanel
from .statusbar import StatusStrip
from .visualizer import Visualizer

STATE_TEXT = {
    "offline": "OFFLINE", "muted": "MUTED", "listening": "LISTENING", "hearing": "HEARING YOU",
    "thinking": "THINKING", "tool": "WORKING", "confirm": "WAITING FOR YOU", "speaking": "SPEAKING",
}
STATE_HINT = {
    "offline": "Cannot reach the backend. Check Settings › Connection.",
    "muted": "Microphone is off. Click the mic or say nothing; it will not hear you.",
    "listening": "Say the name to get its attention.",
    "hearing": "Go on…",
    "thinking": "",
    "tool": "Running a tool on this computer.",
    "confirm": "Say yes, no or always — or use the buttons.",
    "speaking": "Say the name to interrupt.",
}


def make_icon(accent, state="listening") -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = theme.STATE_COLORS.get(state) or accent.name()
    from PySide6.QtGui import QColor
    p.setBrush(QColor(c))
    p.setPen(Qt.NoPen)
    p.drawEllipse(8, 8, 48, 48)
    p.setBrush(QColor("#0e1016"))
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, controller, settings_factory):
        super().__init__()
        self.ctl = controller
        self._settings_factory = settings_factory
        self._settings = None
        self.setWindowTitle("Genesis")
        self.resize(900, 640)
        self.accent = theme.accent_for(self.ctl.persona)

        # ---- centre ------------------------------------------------------
        centre = QWidget()
        centre.setObjectName("root")
        v = QVBoxLayout(centre)
        v.setContentsMargins(18, 12, 18, 12)
        v.setSpacing(6)
        self.persona_label = QLabel(self.ctl.persona.title())
        self.persona_label.setObjectName("persona")
        self.persona_label.setAlignment(Qt.AlignCenter)
        self.state_label = QLabel("OFFLINE")
        self.state_label.setObjectName("state")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.visual = Visualizer()
        self.visual.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.visual.set_style(config.get("visual_style"))
        self.transcript = QLabel("")
        self.transcript.setObjectName("transcript")
        self.transcript.setAlignment(Qt.AlignCenter)
        self.transcript.setWordWrap(True)
        self.transcript.setMinimumHeight(48)
        self.spoken = QLabel("")
        self.spoken.setObjectName("spoken")
        self.spoken.setAlignment(Qt.AlignCenter)
        self.spoken.setWordWrap(True)
        self.spoken.setMinimumHeight(40)
        self.hint = QLabel("")
        self.hint.setObjectName("caption")
        self.hint.setAlignment(Qt.AlignCenter)
        self.approval = ApprovalBar()
        self.approval.decided.connect(self.ctl.resolve_approval)
        v.addWidget(self.persona_label)
        v.addWidget(self.state_label)
        v.addWidget(self.visual, 1)
        v.addWidget(self.transcript)
        v.addWidget(self.spoken)
        v.addWidget(self.approval)
        v.addWidget(self.hint)
        self.setCentralWidget(centre)

        # ---- toolbar -----------------------------------------------------
        tb = QToolBar("main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        self.persona_combo = QComboBox()
        self.persona_combo.setMinimumWidth(120)
        self.persona_combo.currentIndexChanged.connect(self._persona_picked)
        tb.addWidget(QLabel(" Agent "))
        tb.addWidget(self.persona_combo)
        self.mode_combo = QComboBox()
        for key, label in (("wake", "Wake word"), ("push", "Push to talk"), ("always", "Always on"), ("off", "Voice off")):
            self.mode_combo.addItem(label, key)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(config.get("voice_mode"))))
        self.mode_combo.currentIndexChanged.connect(lambda i: self.ctl.set_mode(self.mode_combo.itemData(i)))
        tb.addWidget(QLabel("  Mode "))
        tb.addWidget(self.mode_combo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.ptt = QToolButton()
        self.ptt.setObjectName("ptt")
        self.ptt.setText("● Hold to talk")
        self.ptt.pressed.connect(self.ctl.push_start)
        self.ptt.released.connect(self.ctl.push_end)
        tb.addWidget(self.ptt)
        self.mute_act = QAction("Mute", self, checkable=True)
        self.mute_act.setShortcut(QKeySequence("Ctrl+M"))
        self.mute_act.toggled.connect(self.ctl.set_muted)
        tb.addAction(self.mute_act)
        self.stop_act = QAction("Stop", self)
        self.stop_act.setShortcut(QKeySequence("Escape"))
        self.stop_act.triggered.connect(self.ctl.interrupt)
        tb.addAction(self.stop_act)
        tb.addSeparator()
        self.chat_act = QAction("Chat", self, checkable=True)
        self.chat_act.setShortcut(QKeySequence("Ctrl+T"))
        self.activity_act = QAction("Activity", self, checkable=True)
        self.activity_act.setShortcut(QKeySequence("Ctrl+L"))
        tb.addAction(self.chat_act)
        tb.addAction(self.activity_act)
        self.settings_act = QAction("Settings", self)
        self.settings_act.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_act.triggered.connect(self.open_settings)
        tb.addAction(self.settings_act)

        # ---- docks -------------------------------------------------------
        self.chat = ChatPanel()
        self.chat.submitted.connect(lambda t: self.ctl.submit(t, voice=False))
        self.chat_dock = QDockWidget("Chat", self)
        self.chat_dock.setWidget(self.chat)
        self.chat_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
        self.activity = ActivityPanel()
        self.activity_dock = QDockWidget("Activity", self)
        self.activity_dock.setWidget(self.activity)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.activity_dock)
        self.resizeDocks([self.chat_dock, self.activity_dock], [320, 300], Qt.Horizontal)
        self.chat_act.toggled.connect(self.chat_dock.setVisible)
        self.activity_act.toggled.connect(self.activity_dock.setVisible)
        self.chat_dock.visibilityChanged.connect(lambda v: self.chat_act.setChecked(v) if self.chat_act.isChecked() != v else None)
        self.activity_dock.visibilityChanged.connect(lambda v: self.activity_act.setChecked(v) if self.activity_act.isChecked() != v else None)
        self.chat_dock.setVisible(bool(config.get("show_chat")))
        self.activity_dock.setVisible(bool(config.get("show_activity")))
        self.chat_act.setChecked(bool(config.get("show_chat")))
        self.activity_act.setChecked(bool(config.get("show_activity")))

        # ---- status ------------------------------------------------------
        self.status = StatusStrip()
        self.setStatusBar(self.status)

        # ---- wiring ------------------------------------------------------
        c = self.ctl
        c.state_changed.connect(self._on_state)
        c.level.connect(self.visual.set_level)
        c.partial_text.connect(self._on_partial)
        c.user_message.connect(self._on_user)
        c.assistant_delta.connect(self.chat.append_assistant)
        c.assistant_done.connect(self._on_done)
        c.spoken_sentence.connect(self._on_spoken)
        c.status.connect(self.status.set)
        c.activity.connect(self.activity.add)
        c.approval_needed.connect(self._on_approval)
        c.approval_resolved.connect(self.approval.hide)
        c.personas_loaded.connect(self._on_personas)
        c.persona_changed.connect(self._on_persona)
        c.error.connect(self._on_error)
        c.ui_request.connect(self._on_ui_request)
        config.watch("*", self._on_config)
        self.apply_theme()
        self._on_state(c.state)
        self.setWindowOpacity(config.get("window_opacity"))
        if config.get("always_on_top"):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

    # ------------------------------------------------------------------
    def apply_theme(self):
        self.accent = theme.accent_for(self.ctl.persona)
        QApplication.instance().setStyleSheet(theme.stylesheet(config.get("theme"), self.accent))
        self.visual.set_accent(self.accent)
        self.visual.set_theme(config.get("theme"))
        self.setWindowIcon(make_icon(self.accent))

    def _on_config(self, key, old, new):
        if key in ("theme",):
            self.apply_theme()
        elif key == "visual_style":
            self.visual.set_style(new)
        elif key == "window_opacity":
            self.setWindowOpacity(new)
        elif key == "always_on_top":
            self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(new))
            self.show()
        elif key == "voice_mode":
            i = self.mode_combo.findData(new)
            if i >= 0 and self.mode_combo.currentIndex() != i:
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentIndex(i)
                self.mode_combo.blockSignals(False)
            self.ptt.setVisible(new != "off")

    # ------------------------------------------------------------------
    def _on_state(self, s):
        self.visual.set_state(s)
        self.state_label.setText(STATE_TEXT.get(s, s.upper()))
        if s != "confirm":
            self.hint.setText(STATE_HINT.get(s, ""))
        if s in ("listening", "muted", "offline"):
            self.transcript.setText("")
        if s not in ("speaking",):
            QTimer.singleShot(2500, lambda: self.spoken.setText("") if self.ctl.state not in ("speaking",) else None)
        self.setWindowIcon(make_icon(self.accent, s))
        self.mute_act.blockSignals(True)
        self.mute_act.setChecked(self.ctl.muted)
        self.mute_act.blockSignals(False)

    def _on_partial(self, text):
        self.transcript.setText(text)

    def _on_user(self, text):
        self.transcript.setText(text)
        self.chat.add_user(text)

    def _on_done(self, text, meta):
        self.chat.finish_assistant(text, meta)

    def _on_spoken(self, s):
        self.spoken.setText(s)

    def _on_approval(self, req):
        self.approval.show_request(req, self.persona_label.text())
        self.hint.setText(STATE_HINT["confirm"])
        self.show()
        self.raise_()

    def _on_personas(self, personas):
        self.persona_combo.blockSignals(True)
        self.persona_combo.clear()
        for p in personas:
            self.persona_combo.addItem(p.get("title", p["name"]), p["name"])
        i = self.persona_combo.findData(self.ctl.persona)
        self.persona_combo.setCurrentIndex(max(0, i))
        self.persona_combo.blockSignals(False)
        self._on_persona(self.ctl.persona)

    def _persona_picked(self, i):
        name = self.persona_combo.itemData(i)
        if name:
            self.ctl.set_persona(name)

    def _on_persona(self, name):
        title = next((p.get("title", name) for p in self.ctl.personas if p["name"] == name), name.title())
        self.persona_label.setText(title)
        i = self.persona_combo.findData(name)
        if i >= 0 and self.persona_combo.currentIndex() != i:
            self.persona_combo.blockSignals(True)
            self.persona_combo.setCurrentIndex(i)
            self.persona_combo.blockSignals(False)
        self.apply_theme()
        self.chat.add_system(f"— {title} —")

    def _on_error(self, msg):
        self.status.flash(msg)
        self.chat.add_system(f"⚠ {msg}")

    def _on_ui_request(self, what, value):
        if what == "chat":
            self.chat_act.setChecked(bool(value))
        elif what == "activity":
            self.activity_act.setChecked(bool(value))
        elif what == "settings":
            self.open_settings()
        elif what == "show":
            self.show()
            self.raise_()
            self.activateWindow()

    def open_settings(self, page=None):
        if self._settings is None:
            self._settings = self._settings_factory(self)
        self._settings.open_page(page or "Connection") if page else (self._settings.show(), self._settings.raise_(), self._settings.activateWindow())

    # ------------------------------------------------------------------
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat() and not self.chat.input.hasFocus():
            self.ctl.push_start()
            self.ptt.setDown(True)
            return
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat() and self.ctl.attention.pushed:
            self.ctl.push_end()
            self.ptt.setDown(False)
            return
        super().keyReleaseEvent(ev)

    def closeEvent(self, ev):
        if getattr(self, "tray_enabled", False) and not getattr(self, "_quitting", False):
            ev.ignore()
            self.hide()
            return
        super().closeEvent(ev)
