"""Side panels: the optional chat view, the activity log, the approval
prompt. All of them are dock widgets so you can drag them off or hide
them; the visualizer is the main event."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor, QTextOption
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSplitter, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


class ChatPanel(QWidget):
    """Bubbles plus a text box. Hidden by default; voice is the main path.
    The strip at the top picks the conversation (the backend keeps one
    history per persona per session name)."""
    submitted = Signal(str)
    session_picked = Signal(str)
    new_session = Signal()
    delete_session = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        top = QHBoxLayout()
        self.sessions = QComboBox()
        self.sessions.setEditable(True)
        self.sessions.setInsertPolicy(QComboBox.NoInsert)
        self.sessions.setToolTip("Conversation. Type a new name and press Enter to start one.")
        self.sessions.lineEdit().returnPressed.connect(
            lambda: self.session_picked.emit(self.sessions.currentText()))
        self.sessions.activated.connect(lambda i: self.session_picked.emit(self.sessions.itemText(i)))
        new = QToolButton()
        new.setText("New")
        new.setToolTip("New conversation")
        new.clicked.connect(self.new_session)
        rm = QToolButton()
        rm.setText("Delete")
        rm.setToolTip("Delete this conversation on the backend")
        rm.clicked.connect(lambda: self.delete_session.emit(self.sessions.currentText()))
        top.addWidget(self.sessions, 1)
        top.addWidget(new)
        top.addWidget(rm)
        lay.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.inner.setObjectName("root")
        self.vbox = QVBoxLayout(self.inner)
        self.vbox.setContentsMargins(4, 4, 4, 4)
        self.vbox.setSpacing(8)
        self.vbox.addStretch(1)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type instead of talking…")
        self.input.returnPressed.connect(self._send)
        self.send = QPushButton("Send")
        self.send.setObjectName("primary")
        self.send.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(self.send)
        lay.addLayout(row)
        self._current = None

    def _send(self):
        t = self.input.text().strip()
        if t:
            self.input.clear()
            self.submitted.emit(t)

    def _bubble(self, kind, text):
        f = QFrame()
        f.setObjectName({"user": "bubbleUser", "assistant": "bubbleAssistant"}.get(kind, "bubbleSystem"))
        l = QVBoxLayout(f)
        l.setContentsMargins(10, 7, 10, 7)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if kind == "system":
            lab.setObjectName("hint")
        l.addWidget(lab)
        wrap = QHBoxLayout()
        if kind == "user":
            wrap.addStretch(1)
            wrap.addWidget(f, 4)
        elif kind == "assistant":
            wrap.addWidget(f, 4)
            wrap.addStretch(1)
        else:
            wrap.addWidget(f)
        holder = QWidget()
        holder.setLayout(wrap)
        self.vbox.insertWidget(self.vbox.count() - 1, holder)
        self._scroll_down()
        return lab

    def add_user(self, text):
        self._current = None
        self._bubble("user", text)

    def add_system(self, text):
        self._current = None
        self._bubble("system", text)

    def append_assistant(self, delta):
        if self._current is None:
            if not delta.strip():
                return
            self._current = self._bubble("assistant", "")
        self._current.setText(self._current.text() + delta)
        self._scroll_down()

    def finish_assistant(self, text, meta=None):
        text = (text or "").strip()
        if self._current is None and text:
            self._current = self._bubble("assistant", text)
        elif self._current is not None and text and self._current.text().strip() != text:
            self._current.setText(text)
        if meta and meta.get("interrupted") and self._current is not None and text:
            self._current.setText(self._current.text() + "  …")
        self._current = None

    def clear(self):
        while self.vbox.count() > 1:
            item = self.vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._current = None

    def set_sessions(self, rows: list, current: str):
        self.sessions.blockSignals(True)
        self.sessions.clear()
        names = [r["name"] for r in rows]
        if current not in names:
            names.insert(0, current)
        for n in names:
            self.sessions.addItem(n)
        self.sessions.setCurrentText(current)
        self.sessions.blockSignals(False)

    def load_history(self, rows: list, title: str = ""):
        """Replace the bubbles with the backend's transcript."""
        self.clear()
        if title:
            self.add_system(f"— {title} —")
        for r in rows:
            role, text = r.get("role"), (r.get("content") or "").strip()
            if not text:
                continue
            if role == "user":
                self.add_user(text)
            elif role == "assistant":
                self._current = None
                self._bubble("assistant", text + ("  …" if r.get("interrupted") else ""))
        self._current = None

    def _scroll_down(self):
        bar = self.scroll.verticalScrollBar()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))


class ActivityPanel(QWidget):
    """What it heard, what it ran, what it was refused. Click a row to see
    the full output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        split = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["time", "kind", "what"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 64)
        self.tree.setColumnWidth(1, 70)
        self.tree.currentItemChanged.connect(self._show)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Monospace", 10))
        self.detail.setWordWrapMode(QTextOption.NoWrap)
        self.detail.setPlaceholderText("select a row to see the full output")
        split.addWidget(self.tree)
        split.addWidget(self.detail)
        split.setSizes([260, 180])
        lay.addWidget(split)
        row = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self.tree.clear)
        row.addStretch(1)
        row.addWidget(clear)
        lay.addLayout(row)

    def add(self, entry: dict):
        it = QTreeWidgetItem([entry.get("ts", ""), entry.get("kind", ""), entry.get("title", "")])
        it.setData(0, Qt.UserRole, entry.get("detail", ""))
        kind = entry.get("kind")
        colour = {"error": "#ff6b6b", "refused": "#ff6b6b", "denied": "#ff6b6b",
                  "ask": "#ffb84f", "tool": "#ffb84f", "allowed": "#4fd1a1",
                  "command": "#c98cff", "mod": "#c98cff"}.get(kind)
        if colour:
            from PySide6.QtGui import QBrush, QColor
            it.setForeground(1, QBrush(QColor(colour)))
        if kind == "heard" and entry.get("title", "").startswith("(not for me)"):
            it.setForeground(2, QBrush(QColor("#8b91a3")))
        self.tree.addTopLevelItem(it)
        if self.tree.topLevelItemCount() > 500:
            self.tree.takeTopLevelItem(0)
        self.tree.scrollToBottom()

    def _show(self, cur, prev):
        if cur:
            self.detail.setPlainText(cur.data(0, Qt.UserRole) or cur.text(2))


class ApprovalBar(QFrame):
    """Shown under the visualizer when a tool needs a yes. Also answerable
    by voice: yes / no / always."""
    decided = Signal(bool, bool)     # allow, always

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bubbleAssistant")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.title = QLabel("")
        self.title.setObjectName("h2")
        self.cmd = QLabel("")
        self.cmd.setFont(QFont("Monospace", 11))
        self.cmd.setWordWrap(True)
        self.cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.risk = QLabel("")
        self.risk.setObjectName("hint")
        row = QHBoxLayout()
        self.allow = QPushButton("Allow")
        self.allow.setObjectName("primary")
        self.always = QPushButton("Always allow this")
        self.deny = QPushButton("Deny")
        self.deny.setObjectName("danger")
        self.allow.clicked.connect(lambda: self.decided.emit(True, False))
        self.always.clicked.connect(lambda: self.decided.emit(True, True))
        self.deny.clicked.connect(lambda: self.decided.emit(False, False))
        row.addWidget(self.allow)
        row.addWidget(self.always)
        row.addStretch(1)
        row.addWidget(self.deny)
        lay.addWidget(self.title)
        lay.addWidget(self.cmd)
        lay.addWidget(self.risk)
        lay.addLayout(row)
        self.hide()

    def show_request(self, req: dict, persona_title: str):
        self.title.setText(f"{persona_title} wants to run")
        self.cmd.setText(req.get("summary", ""))
        risk = req.get("risk", "mutating")
        self.risk.setText({
            "privileged": "Needs root. A system password prompt will appear.",
            "mutating": "This changes something on this computer.",
        }.get(risk, "") + "  Say yes, no, or always.")
        self.always.setVisible(req.get("tool") == "run_command")
        self.show()
