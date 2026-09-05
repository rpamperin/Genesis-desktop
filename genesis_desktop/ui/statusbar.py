"""The status strip: backend, agent, microphone, speech engines, mode,
and what tool is running. Each is a pill; the live ones light up."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar

ORDER = ["backend", "user", "agent", "mode", "mic", "stt", "tts", "tool", "stats"]
PREFIX = {"backend": "⚙ ", "user": "👤 ", "agent": "◉ ", "mode": "◎ ", "mic": "🎙 ", "stt": "👂 ",
          "tts": "🔊 ", "tool": "⚡ ", "stats": "📈 "}


class StatusStrip(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.pills = {}
        for key in ORDER:
            lab = QLabel("")
            lab.setObjectName("pill")
            lab.setProperty("live", "false")
            lab.hide()
            self.pills[key] = lab
            self.addWidget(lab)
        self.message = QLabel("")
        self.message.setObjectName("hint")
        self.addPermanentWidget(self.message)

    def set(self, key: str, text: str, live: bool = None):
        lab = self.pills.get(key)
        if not lab:
            return
        if not text:
            lab.hide()
            return
        lab.setText(PREFIX.get(key, "") + text)
        lab.setToolTip(text)
        lab.show()
        if live is None:
            live = key in ("agent",) or (key == "backend" and "offline" not in text and "connecting" not in text) \
                or (key == "mic" and text == "mic on")
        lab.setProperty("live", "true" if live else "false")
        lab.style().unpolish(lab)
        lab.style().polish(lab)

    def flash(self, text: str):
        self.message.setText(text)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(6000, lambda: self.message.setText("") if self.message.text() == text else None)
