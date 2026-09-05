"""The settings window. A separate top-level window with a page list on
the left, so it never crowds the main view.

Pages:
    Connection   backend URL, tokens, autostart
    Agent        which persona, wake words, greeting, per-persona voice
    Voice        listening mode, speech engines, devices, downloads
    Local tools  policy, always-allow list, work dir, root actions
    Local mods   enable/disable mods in ~/.config/genesis-desktop/mods
    Backend      the backend's own settings and mods (admin token needed)
    Appearance   theme, visualizer style, panels, tray
    Diagnostics  what is installed, what is missing, log location

Local settings save on change. Backend settings post to the admin API and
show the result, since the backend validates ranges itself.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .. import client as client_mod
from .. import config, mods, tools
from ..voice import audio, stt, tts


class _Async(QObject):
    done = Signal(object, str)      # result, error

    def run(self, fn):
        def w():
            try:
                self.done.emit(fn(), "")
            except Exception as e:
                self.done.emit(None, str(e))
        threading.Thread(target=w, daemon=True).start()


def _hint(text):
    l = QLabel(text)
    l.setObjectName("hint")
    l.setWordWrap(True)
    return l


def _page(title, subtitle=""):
    outer = QScrollArea()
    outer.setWidgetResizable(True)
    outer.setFrameShape(QScrollArea.NoFrame)
    w = QWidget()
    w.setObjectName("root")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(10)
    h = QLabel(title)
    h.setObjectName("h1")
    lay.addWidget(h)
    if subtitle:
        lay.addWidget(_hint(subtitle))
    outer.setWidget(w)
    return outer, lay


# ----------------------------------------------------------------------
# bound widgets: each one reads config on build and writes on change
# ----------------------------------------------------------------------
def bound_line(key, secret=False, placeholder=""):
    e = QLineEdit(str(config.get(key) or ""))
    e.setPlaceholderText(placeholder)
    if secret:
        e.setEchoMode(QLineEdit.Password)
    e.editingFinished.connect(lambda: _save(key, e.text(), e))
    return e


def bound_check(key, label):
    c = QCheckBox(label)
    c.setChecked(bool(config.get(key)))
    c.toggled.connect(lambda v: _save(key, v, c))
    return c


def bound_combo(key, choices, labels=None):
    c = QComboBox()
    for ch in choices:
        c.addItem((labels or {}).get(ch, ch), ch)
    cur = config.get(key)
    if cur in choices:
        c.setCurrentIndex(choices.index(cur))
    c.currentIndexChanged.connect(lambda i: _save(key, c.itemData(i), c))
    return c


def bound_spin(key, lo, hi, step=1, double=False, suffix=""):
    s = QDoubleSpinBox() if double else QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    if double:
        s.setDecimals(3 if hi <= 1 else 2)
    s.setValue(config.get(key))
    if suffix:
        s.setSuffix(suffix)
    s.editingFinished.connect(lambda: _save(key, s.value(), s))
    return s


def bound_list(key, placeholder=""):
    e = QLineEdit(", ".join(config.get(key)))
    e.setPlaceholderText(placeholder)
    e.editingFinished.connect(lambda: _save(key, [p.strip() for p in e.text().split(",") if p.strip()], e))
    return e


def _save(key, value, widget=None):
    try:
        config.set(key, value)
    except (ValueError, TypeError) as e:
        if widget:
            QMessageBox.warning(widget, "Not saved", str(e))


# ----------------------------------------------------------------------
class SettingsWindow(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.setWindowTitle("Genesis settings")
        self.setMinimumSize(880, 600)
        self.resize(980, 680)
        self.setWindowFlag(Qt.Window, True)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        self.stack = QStackedWidget()
        root.addWidget(self.nav)
        root.addWidget(self.stack, 1)
        pages = [
            ("Connection", self._connection_page),
            ("Agent", self._agent_page),
            ("Voice", self._voice_page),
            ("Local tools", self._tools_page),
            ("Local mods", self._mods_page),
            ("Backend", self._backend_page),
            ("Appearance", self._appearance_page),
            ("Diagnostics", self._diag_page),
        ]
        for name, builder in pages:
            self.nav.addItem(QListWidgetItem(name))
            self.stack.addWidget(builder())
        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)

    def _switch(self, row):
        self.stack.setCurrentIndex(row)
        refresh = getattr(self.stack.widget(row), "refresh", None)
        if refresh:
            refresh()

    def open_page(self, name):
        for i in range(self.nav.count()):
            if self.nav.item(i).text() == name:
                self.nav.setCurrentRow(i)
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    def _connection_page(self):
        page, lay = _page("Connection", "Where the Genesis backend runs. Tokens are only needed if the backend has them set.")
        form = QFormLayout()
        form.addRow("Backend URL", bound_line("backend_url", placeholder="http://127.0.0.1:8080"))
        form.addRow("API token", bound_line("api_token", secret=True, placeholder="X-Genesis-Token"))
        form.addRow("Admin token", bound_line("admin_token", secret=True, placeholder="X-Genesis-Admin (for the Backend page)"))
        form.addRow("Session name", bound_line("session"))
        form.addRow("User", bound_line("user"))
        lay.addLayout(form)
        row = QHBoxLayout()
        test = QPushButton("Test connection")
        self.conn_result = QLabel("")
        self.conn_result.setObjectName("hint")
        test.clicked.connect(self._test_connection)
        row.addWidget(test)
        row.addWidget(self.conn_result, 1)
        lay.addLayout(row)

        g = QGroupBox("Run the backend from here")
        gl = QVBoxLayout(g)
        gl.addWidget(bound_check("autostart_backend", "Start the backend when this app starts (if it is not already reachable)"))
        f2 = QFormLayout()
        f2.addRow("Genesis folder", self._dir_picker("backend_dir"))
        f2.addRow("Command", bound_line("backend_command", placeholder="python -m genesis serve"))
        gl.addLayout(f2)
        gl.addWidget(_hint("The command runs inside the Genesis folder. If it uses a virtualenv, put the full path: .venv/bin/python -m genesis serve"))
        lay.addWidget(g)
        lay.addStretch(1)
        return page

    def _dir_picker(self, key):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        e = bound_line(key)
        b = QPushButton("Browse…")

        def pick():
            d = QFileDialog.getExistingDirectory(self, "Choose folder", e.text() or str(Path.home()))
            if d:
                e.setText(d)
                _save(key, d, e)
        b.clicked.connect(pick)
        h.addWidget(e, 1)
        h.addWidget(b)
        return w

    def _test_connection(self):
        self.conn_result.setText("testing…")
        a = _Async(self)

        def done(res, err):
            if err:
                self.conn_result.setText(f"✗ {err}")
            else:
                self.conn_result.setText(
                    f"✓ {res.get('provider')} · {res.get('model')} · personas: {', '.join(res.get('personas', []))}"
                    f" · model {'ok' if res.get('ok') else 'unreachable: ' + str(res.get('detail'))}")
                self.ctl.connect()
        a.done.connect(done)
        a.run(lambda: client_mod.GenesisClient().health())

    # ------------------------------------------------------------------
    def _agent_page(self):
        page, lay = _page("Agent", "Who answers when you talk. Each persona keeps its own history and voice.")
        self.persona_list = QListWidget()
        self.persona_list.setMaximumHeight(160)
        lay.addWidget(self.persona_list)
        self.persona_info = _hint("")
        lay.addWidget(self.persona_info)
        self.persona_list.currentRowChanged.connect(self._pick_persona)
        lay.addWidget(bound_check("greet_on_start", "Say the greeting when the app starts"))

        g = QGroupBox("Wake words")
        gl = QVBoxLayout(g)
        gl.addWidget(bound_list("wake_words", "empty = persona names + genesis"))
        gl.addWidget(_hint("Comma separated. Say one of these first and the rest of the sentence goes to the assistant. "
                           "\"Hey Alfred\" and \"OK Alfred\" work too."))
        lay.addWidget(g)

        g2 = QGroupBox("Voice per persona")
        self.voice_form = QFormLayout(g2)
        lay.addWidget(g2)
        lay.addWidget(_hint("Piper voice names, downloaded on the Voice page. Leave blank to use the backend's choice."))
        lay.addStretch(1)
        page.refresh = self._refresh_personas
        return page

    def _refresh_personas(self):
        self.persona_list.blockSignals(True)
        self.persona_list.clear()
        for p in self.ctl.personas or [{"name": config.get("persona"), "title": config.get("persona").title()}]:
            it = QListWidgetItem(f"{p.get('title', p['name'])}   —   {', '.join(p.get('tags', []))}")
            it.setData(Qt.UserRole, p["name"])
            self.persona_list.addItem(it)
            if p["name"] == self.ctl.persona:
                self.persona_list.setCurrentItem(it)
        self.persona_list.blockSignals(False)
        self._pick_persona(self.persona_list.currentRow(), apply=False)
        while self.voice_form.rowCount():
            self.voice_form.removeRow(0)
        overrides = dict(config.get("persona_voices"))
        for p in self.ctl.personas:
            c = QComboBox()
            c.setEditable(True)
            c.addItem("")
            for v in tts.PIPER_VOICES:
                c.addItem(v)
            c.setCurrentText(overrides.get(p["name"], ""))

            def save(text, name=p["name"]):
                cur = dict(config.get("persona_voices"))
                if text.strip():
                    cur[name] = text.strip()
                else:
                    cur.pop(name, None)
                config.set("persona_voices", cur)
            c.currentTextChanged.connect(save)
            self.voice_form.addRow(f"{p.get('title', p['name'])} (backend: {p.get('voice', '?')})", c)

    def _pick_persona(self, row, apply=True):
        it = self.persona_list.item(row)
        if not it:
            return
        name = it.data(Qt.UserRole)
        info = next((p for p in self.ctl.personas if p["name"] == name), {})
        self.persona_info.setText(
            f"model: {info.get('model', '?')} · temperature: {info.get('temperature', '?')} · "
            f"backend tools: {'on' if info.get('tools') else 'off'} · greeting: {info.get('greeting', '')!r}")
        if apply and name != self.ctl.persona:
            self.ctl.set_persona(name)

    # ------------------------------------------------------------------
    def _voice_page(self):
        page, lay = _page("Voice", "How it listens and how it talks. Everything can run offline.")
        g = QGroupBox("Listening")
        f = QFormLayout(g)
        f.addRow("Mode", bound_combo("voice_mode", ["wake", "push", "always", "off"], {
            "wake": "Wake word  —  say the name first", "push": "Push to talk  —  hold the button or Space",
            "always": "Always listening", "off": "Voice off  —  text only"}))
        f.addRow("", bound_check("require_name_in_always", "In always mode, still only answer when named"))
        f.addRow("Follow-up window", bound_spin("follow_up_seconds", 0, 120, 1, double=True, suffix=" s"))
        f.addRow("", bound_check("barge_in", "Let me interrupt by saying the name while it is talking"))
        lay.addWidget(g)

        g = QGroupBox("Microphone")
        f = QFormLayout(g)
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("system default", "")
        for i, n in audio.input_devices():
            self.mic_combo.addItem(n, str(i))
        cur = config.get("mic_device")
        idx = self.mic_combo.findData(cur)
        self.mic_combo.setCurrentIndex(max(0, idx))
        self.mic_combo.currentIndexChanged.connect(lambda i: _save("mic_device", self.mic_combo.itemData(i)))
        f.addRow("Input device", self.mic_combo)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.ctl.level.connect(lambda v: self.level_bar.setValue(int(min(1.0, v * 6) * 100)))
        f.addRow("Level", self.level_bar)
        thr = bound_spin("vad_threshold", 0.001, 0.5, 0.005, double=True)
        f.addRow("Speech threshold", thr)
        f.addRow("End of sentence after", bound_spin("silence_ms", 200, 5000, 100, suffix=" ms"))
        f.addRow("Longest utterance", bound_spin("max_utterance_s", 3, 120, 1, suffix=" s"))
        lay.addWidget(g)
        lay.addWidget(_hint("If it triggers on background noise, raise the threshold. If it cuts you off mid-sentence, raise the end-of-sentence delay."))

        g = QGroupBox("Speech recognition")
        f = QFormLayout(g)
        f.addRow("Engine", bound_combo("stt_engine", ["auto", "vosk", "whisper", "backend"], {
            "auto": "Automatic", "vosk": "Vosk (offline, fast)", "whisper": "Whisper (offline, accurate)",
            "backend": "Backend /transcribe"}))
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        self.vosk_status = QLabel("")
        self.vosk_status.setObjectName("hint")
        dl = QPushButton("Download Vosk model (40 MB)")
        dl.clicked.connect(self._download_vosk)
        rh.addWidget(self.vosk_status, 1)
        rh.addWidget(dl)
        f.addRow("Vosk model", row)
        f.addRow("Vosk folder", self._dir_picker("vosk_model"))
        f.addRow("Whisper model", bound_line("whisper_model", placeholder="base.en"))
        lay.addWidget(g)

        g = QGroupBox("Speech output")
        f = QFormLayout(g)
        f.addRow("Engine", bound_combo("tts_engine", ["auto", "piper", "backend", "espeak", "qt", "off"], {
            "auto": "Automatic", "piper": "Piper (offline, natural)", "backend": "Backend /speak",
            "espeak": "espeak-ng (robotic)", "qt": "System (speech-dispatcher)", "off": "Off"}))
        f.addRow("", bound_check("speak_replies", "Read replies aloud"))
        f.addRow("", bound_check("speak_tool_activity", "Say \"working on it\" for slow tools"))
        rate = QSlider(Qt.Horizontal)
        rate.setRange(50, 200)
        rate.setValue(int(config.get("tts_rate") * 100))
        rate.sliderReleased.connect(lambda: _save("tts_rate", rate.value() / 100))
        f.addRow("Speed", rate)
        self.out_combo = QComboBox()
        self.out_combo.addItem("system default", "")
        for i, n in audio.output_devices():
            self.out_combo.addItem(n, str(i))
        idx = self.out_combo.findData(config.get("output_device"))
        self.out_combo.setCurrentIndex(max(0, idx))
        self.out_combo.currentIndexChanged.connect(lambda i: _save("output_device", self.out_combo.itemData(i)))
        f.addRow("Output device", self.out_combo)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        self.piper_combo = QComboBox()
        for v in tts.PIPER_VOICES:
            self.piper_combo.addItem(v)
        dlv = QPushButton("Download voice")
        dlv.clicked.connect(self._download_voice)
        test = QPushButton("Test")
        test.clicked.connect(lambda: self.ctl.say("Hello. This is how I sound."))
        rh.addWidget(self.piper_combo, 1)
        rh.addWidget(dlv)
        rh.addWidget(test)
        f.addRow("Piper voices", row)
        f.addRow("Voice folder", self._dir_picker("piper_voice_dir"))
        self.voice_status = QLabel("")
        self.voice_status.setObjectName("hint")
        f.addRow("", self.voice_status)
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        self.dl_bar.hide()
        f.addRow("", self.dl_bar)
        lay.addWidget(g)
        lay.addStretch(1)
        page.refresh = self._refresh_voice
        return page

    def _refresh_voice(self):
        ok, msg = stt.vosk_ready()
        self.vosk_status.setText(("✓ " if ok else "✗ ") + msg)
        have = sorted(p.stem.replace(".onnx", "") for p in config.piper_voice_dir().glob("*.onnx")) \
            if config.piper_voice_dir().exists() else []
        self.voice_status.setText("downloaded: " + (", ".join(have) or "none") +
                                  f"   ·   engine: {self.ctl.speaker.engine or 'none'} ({self.ctl.speaker.engine_note})")

    def _download(self, fn, label):
        self.dl_bar.show()
        self.dl_bar.setValue(0)
        a = _Async(self)
        prog = _Async(self)
        prog.done.connect(lambda v, e: self.dl_bar.setValue(int(v * 100)))

        def done(res, err):
            self.dl_bar.hide()
            if err:
                QMessageBox.warning(self, "Download failed", f"{label}: {err}")
            else:
                self.ctl._configure_speech()
                self._refresh_voice()
        a.done.connect(done)
        a.run(lambda: fn(progress=lambda v: prog.done.emit(v, "")))

    def _download_vosk(self):
        self._download(stt.download_vosk_model, "Vosk model")

    def _download_voice(self):
        name = self.piper_combo.currentText()
        self._download(lambda progress: tts.download_piper_voice(name, progress), name)

    # ------------------------------------------------------------------
    def _tools_page(self):
        page, lay = _page("Local tools", "What the assistant may do on this computer. Tools run here, not on the backend.")
        lay.addWidget(bound_check("local_tools_enabled", "Offer local tools to the assistant"))
        g = QGroupBox("Permission policy")
        f = QFormLayout(g)
        f.addRow("Policy", bound_combo("tool_policy", ["safe", "ask", "trusted"], {
            "safe": "Safe  —  read-only only, refuse changes",
            "ask": "Ask  —  read-only runs, changes need a yes",
            "trusted": "Trusted  —  run everything, root still prompts for a password"}))
        f.addRow("", bound_check("allow_privileged", "Allow root actions through pkexec (password prompt)"))
        f.addRow("Tool timeout", bound_spin("tool_timeout", 1, 600, 5, suffix=" s"))
        f.addRow("Work directory", self._dir_picker("work_dir"))
        lay.addWidget(g)
        lay.addWidget(_hint("Relative paths in tools resolve against the work directory. Empty means your home folder."))

        g = QGroupBox("Always allowed commands")
        gl = QVBoxLayout(g)
        self.allow_list = QListWidget()
        self.allow_list.setMaximumHeight(140)
        gl.addWidget(self.allow_list)
        row = QHBoxLayout()
        rm = QPushButton("Remove selected")
        clr = QPushButton("Clear all")
        rm.clicked.connect(self._remove_allow)
        clr.clicked.connect(lambda: (config.set("tool_always_allow", []), self._refresh_tools()))
        row.addWidget(rm)
        row.addWidget(clr)
        row.addStretch(1)
        gl.addLayout(row)
        lay.addWidget(g)

        g = QGroupBox("Available tools")
        gl = QVBoxLayout(g)
        self.tool_tree = QTreeWidget()
        self.tool_tree.setHeaderLabels(["tool", "from", "description"])
        self.tool_tree.setRootIsDecorated(False)
        gl.addWidget(self.tool_tree)
        lay.addWidget(g)
        page.refresh = self._refresh_tools
        return page

    def _refresh_tools(self):
        self.allow_list.clear()
        for c in config.get("tool_always_allow"):
            self.allow_list.addItem(c)
        self.tool_tree.clear()
        for t in tools.REGISTRY.values():
            self.tool_tree.addTopLevelItem(QTreeWidgetItem([t.name, t.origin, t.spec["function"].get("description", "")[:120]]))
        self.tool_tree.resizeColumnToContents(0)
        self.tool_tree.resizeColumnToContents(1)

    def _remove_allow(self):
        cur = self.allow_list.currentItem()
        if cur:
            config.set("tool_always_allow", [c for c in config.get("tool_always_allow") if c != cur.text()])
            self._refresh_tools()

    # ------------------------------------------------------------------
    def _mods_page(self):
        page, lay = _page("Local mods", f"Drop-in extensions that run in this app. Folder: {config.MODS_DIR}")
        self.mod_tree = QTreeWidget()
        self.mod_tree.setHeaderLabels(["enabled", "mod", "status", "description"])
        self.mod_tree.setRootIsDecorated(False)
        self.mod_tree.itemChanged.connect(self._toggle_mod)
        lay.addWidget(self.mod_tree, 1)
        self.mod_error = QPlainTextEdit()
        self.mod_error.setReadOnly(True)
        self.mod_error.setMaximumHeight(120)
        self.mod_error.setFont(QFont("Monospace", 9))
        self.mod_error.setPlaceholderText("load errors show here")
        self.mod_tree.currentItemChanged.connect(
            lambda c, p: self.mod_error.setPlainText((c.data(0, Qt.UserRole) or "") if c else ""))
        lay.addWidget(self.mod_error)
        row = QHBoxLayout()
        reload = QPushButton("Reload mods")
        reload.clicked.connect(lambda: (mods.reload_all(), self._refresh_mods()))
        openf = QPushButton("Open mods folder")
        openf.clicked.connect(lambda: subprocess.Popen(["xdg-open", str(config.MODS_DIR)]))
        row.addWidget(reload)
        row.addWidget(openf)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_hint("A mod is a folder with a mod.py. It can add tools, voice commands and hooks. "
                            "See the example mod for everything it can do."))
        page.refresh = self._refresh_mods
        return page

    def _refresh_mods(self):
        self.mod_tree.blockSignals(True)
        self.mod_tree.clear()
        for m in mods.discover():
            it = QTreeWidgetItem(["", m["name"],
                                  "loaded" if m["loaded"] else ("error" if m["error"] else ("enabled" if m["enabled"] else "off")),
                                  m["doc"]])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if m["enabled"] else Qt.Unchecked)
            it.setData(0, Qt.UserRole, m["error"] or "")
            self.mod_tree.addTopLevelItem(it)
        self.mod_tree.resizeColumnToContents(1)
        self.mod_tree.blockSignals(False)

    def _toggle_mod(self, item, col):
        if col != 0:
            return
        name = item.text(1)
        if item.checkState(0) == Qt.Checked:
            ok, err = mods.enable(name)
            if not ok:
                QMessageBox.warning(self, "Mod failed to load", err or "")
        else:
            mods.disable(name)
        self._refresh_mods()

    # ------------------------------------------------------------------
    def _backend_page(self):
        page, lay = _page("Backend", "The backend's own settings, edited through its admin API. Needs the admin token.")
        self.be_status = _hint("")
        lay.addWidget(self.be_status)
        self.be_tree = QTreeWidget()
        self.be_tree.setHeaderLabels(["setting", "value", "source", "notes"])
        self.be_tree.setRootIsDecorated(False)
        self.be_tree.itemDoubleClicked.connect(self._edit_backend)
        lay.addWidget(self.be_tree, 2)
        lay.addWidget(_hint("Double-click a value to change it. embed_model and embed_provider need a reindex and are changed from the backend's own tools."))
        g = QGroupBox("Backend mods")
        gl = QVBoxLayout(g)
        self.be_mods = QTreeWidget()
        self.be_mods.setHeaderLabels(["enabled", "mod", "loaded", "description"])
        self.be_mods.setRootIsDecorated(False)
        self.be_mods.itemChanged.connect(self._toggle_backend_mod)
        gl.addWidget(self.be_mods)
        lay.addWidget(g, 1)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_backend)
        reindex = QPushButton("Reindex documents")
        reindex.clicked.connect(self._reindex)
        row.addWidget(refresh)
        row.addWidget(reindex)
        row.addStretch(1)
        lay.addLayout(row)
        page.refresh = self._refresh_backend
        return page

    def _refresh_backend(self):
        self.be_status.setText("loading…")
        a = _Async(self)

        def done(res, err):
            if err:
                self.be_status.setText(f"✗ {err}")
                return
            settings, modlist = res
            self.be_status.setText(f"✓ {self.ctl.client.base_url}")
            self.be_tree.clear()
            for k, v in settings.items():
                notes = []
                sch = v.get("schema", {})
                if sch.get("choices"):
                    notes.append("one of " + ", ".join(map(str, sch["choices"])))
                if sch.get("min") is not None:
                    notes.append(f"{sch['min']}–{sch['max']}")
                if v.get("needs_reindex"):
                    notes.append("needs reindex")
                it = QTreeWidgetItem([k, str(v["value"]), v.get("source", ""), "; ".join(notes)])
                it.setData(0, Qt.UserRole, v)
                self.be_tree.addTopLevelItem(it)
            self.be_tree.resizeColumnToContents(0)
            self.be_tree.resizeColumnToContents(1)
            self.be_mods.blockSignals(True)
            self.be_mods.clear()
            for m in modlist:
                it = QTreeWidgetItem(["", m["name"], "yes" if m.get("loaded") else "no", m.get("doc", "")])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if m.get("enabled") else Qt.Unchecked)
                self.be_mods.addTopLevelItem(it)
            self.be_mods.blockSignals(False)
        a.done.connect(done)
        c = self.ctl.client
        a.run(lambda: (c.admin_settings(), c.admin_mods()))

    def _edit_backend(self, item, col):
        key = item.text(0)
        meta = item.data(0, Qt.UserRole) or {}
        sch = meta.get("schema", {})
        from PySide6.QtWidgets import QInputDialog
        if sch.get("choices"):
            val, ok = QInputDialog.getItem(self, key, key, [str(c) for c in sch["choices"]],
                                           max(0, [str(c) for c in sch["choices"]].index(str(meta["value"]))
                                               if str(meta["value"]) in map(str, sch["choices"]) else 0), False)
        elif sch.get("type") == "bool":
            val, ok = QInputDialog.getItem(self, key, key, ["true", "false"], 0 if meta["value"] else 1, False)
        else:
            val, ok = QInputDialog.getText(self, key, f"{key} ({sch.get('type', 'text')})", text=str(meta["value"]))
        if not ok:
            return
        a = _Async(self)

        def done(res, err):
            if err:
                QMessageBox.warning(self, "Backend refused", err)
            self._refresh_backend()
        a.done.connect(done)
        a.run(lambda: self.ctl.client.admin_set(key, val))

    def _toggle_backend_mod(self, item, col):
        if col != 0:
            return
        name = item.text(1)
        enabled = item.checkState(0) == Qt.Checked
        a = _Async(self)
        a.done.connect(lambda r, e: (QMessageBox.warning(self, "Backend refused", e) if e else None,
                                     self._refresh_backend()))
        a.run(lambda: self.ctl.client.admin_mod_enable(name, enabled))

    def _reindex(self):
        self.be_status.setText("reindexing… this can take a while")
        a = _Async(self)
        a.done.connect(lambda r, e: self.be_status.setText(f"✗ {e}" if e else f"✓ reindexed: {r}"))
        a.run(lambda: self.ctl.client.admin_reindex())

    # ------------------------------------------------------------------
    def _appearance_page(self):
        page, lay = _page("Appearance")
        f = QFormLayout()
        f.addRow("Theme", bound_combo("theme", ["dark", "light"], {"dark": "Dark", "light": "Light"}))
        f.addRow("Visualizer", bound_combo("visual_style", ["orb", "bars", "ring"], {
            "orb": "Orb  —  a living blob", "bars": "Bars  —  spectrum style", "ring": "Ring  —  radial"}))
        op = QSlider(Qt.Horizontal)
        op.setRange(30, 100)
        op.setValue(int(config.get("window_opacity") * 100))
        op.sliderReleased.connect(lambda: _save("window_opacity", op.value() / 100))
        f.addRow("Window opacity", op)
        lay.addLayout(f)
        lay.addWidget(bound_check("show_chat", "Show the chat panel at startup"))
        lay.addWidget(bound_check("show_activity", "Show the activity panel at startup"))
        lay.addWidget(bound_check("always_on_top", "Keep the window above others"))
        lay.addWidget(bound_check("start_in_tray", "Start hidden in the system tray"))
        lay.addWidget(bound_check("transcript_log", "Keep a transcript log in " + str(config.LOG_DIR)))
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------
    def _diag_page(self):
        page, lay = _page("Diagnostics", "What is installed and what is missing.")
        self.diag = QPlainTextEdit()
        self.diag.setReadOnly(True)
        self.diag.setFont(QFont("Monospace", 10))
        lay.addWidget(self.diag, 1)
        row = QHBoxLayout()
        b = QPushButton("Run checks")
        b.clicked.connect(self._run_diag)
        logs = QPushButton("Open log folder")
        logs.clicked.connect(lambda: subprocess.Popen(["xdg-open", str(config.LOG_DIR)]))
        row.addWidget(b)
        row.addWidget(logs)
        row.addStretch(1)
        lay.addLayout(row)
        page.refresh = self._run_diag
        return page

    def _run_diag(self):
        from .. import doctor
        self.diag.setPlainText("checking…")
        a = _Async(self)
        a.done.connect(lambda r, e: self.diag.setPlainText(r or e))
        a.run(lambda: doctor.report(self.ctl))
