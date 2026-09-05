"""Create or edit a persona on the backend (admin API).

Builtins (Alfred, Yui, House) keep their identity: title and system prompt
are read-only for them; everything else is a style knob the backend lets
you change. Custom personas are fully editable and can be deleted.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QVBoxLayout)

from ..voice import tts

GENDERS = ["", "male", "female"]


class PersonaEditor(QDialog):
    def __init__(self, persona: dict | None, parent=None):
        super().__init__(parent)
        self.persona = persona or {}
        builtin = bool(self.persona.get("builtin"))
        creating = not self.persona
        self.setWindowTitle("New persona" if creating else f"Edit {self.persona.get('title') or self.persona.get('name')}")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(self.persona.get("name", ""))
        self.name.setPlaceholderText("short lowercase id, e.g. nurse")
        self.name.setEnabled(creating)
        form.addRow("Name (id)", self.name)
        self.title = QLineEdit(self.persona.get("title", ""))
        self.title.setEnabled(not builtin)
        form.addRow("Title", self.title)
        self.avatar = QLineEdit(self.persona.get("avatar", ""))
        self.avatar.setPlaceholderText("an emoji, e.g. 🩺")
        self.avatar.setMaximumWidth(80)
        form.addRow("Avatar", self.avatar)
        self.accent = QLineEdit(self.persona.get("accent_color", ""))
        self.accent.setPlaceholderText("#rrggbb")
        self.accent.setMaximumWidth(120)
        form.addRow("Accent colour", self.accent)
        self.system = QPlainTextEdit(self.persona.get("system", ""))
        self.system.setPlaceholderText("Who this persona is and how it should answer.")
        self.system.setMinimumHeight(140)
        self.system.setEnabled(not builtin)
        form.addRow("System prompt", self.system)
        if builtin:
            form.addRow("", QLabel("Built-in persona: title and prompt are fixed on the backend."))
        self.greeting = QLineEdit(self.persona.get("greeting", ""))
        form.addRow("Greeting", self.greeting)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(float(self.persona.get("temperature") or 0.5))
        form.addRow("Temperature", self.temperature)
        self.tools = QCheckBox("May use the backend's tools")
        self.tools.setChecked(bool(self.persona.get("tools")))
        form.addRow("", self.tools)
        self.voice = QComboBox()
        self.voice.setEditable(True)
        for v in tts.PIPER_VOICES:
            self.voice.addItem(v)
        self.voice.setCurrentText(self.persona.get("voice", "en_US-amy-medium"))
        form.addRow("Voice", self.voice)
        self.gender = QComboBox()
        self.gender.addItems(GENDERS)
        self.gender.setCurrentText(self.persona.get("voice_gender", "") or "")
        form.addRow("Voice gender", self.gender)
        self.pitch = QDoubleSpinBox()
        self.pitch.setRange(0.3, 2.0)
        self.pitch.setSingleStep(0.05)
        self.pitch.setValue(float(self.persona.get("voice_pitch") or 1.0))
        form.addRow("Voice pitch", self.pitch)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0.5, 2.0)
        self.rate.setSingleStep(0.05)
        self.rate.setValue(float(self.persona.get("voice_rate") or 1.0))
        form.addRow("Voice speed", self.rate)
        self.tags = QLineEdit(", ".join(self.persona.get("tags", []) or []))
        form.addRow("Tags", self.tags)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.result_data = None

    def _accept(self):
        name = self.name.text().strip().lower()
        if not self.persona and not name.replace("_", "").replace("-", "").isalnum():
            QMessageBox.warning(self, "Name", "Use letters, digits, - or _ for the id.")
            return
        builtin = bool(self.persona.get("builtin"))
        data = {
            "greeting": self.greeting.text(),
            "temperature": self.temperature.value(),
            "tools": self.tools.isChecked(),
            "voice": self.voice.currentText().strip(),
            "voice_gender": self.gender.currentText(),
            "voice_pitch": self.pitch.value(),
            "voice_rate": self.rate.value(),
            "tags": [t.strip() for t in self.tags.text().split(",") if t.strip()],
            "avatar": self.avatar.text().strip(),
            "accent_color": self.accent.text().strip(),
        }
        if not builtin:
            data["title"] = self.title.text().strip()
            data["system"] = self.system.toPlainText().strip()
            if not data["system"]:
                QMessageBox.warning(self, "System prompt", "A persona needs a system prompt.")
                return
        if not self.persona:
            data["name"] = name
        self.result_data = data
        self.accept()
