"""The state machine.

    OFFLINE   no backend
    MUTED     microphone off
    LISTENING waiting for the wake word
    HEARING   the user is talking to me
    THINKING  the model is working
    TOOL      a local tool is running
    CONFIRM   waiting for the user to allow or deny a tool
    SPEAKING  reading the reply out

Every thread (microphone, HTTP stream, tools, speech) reports through Qt
signals on the Bridge, so the UI and the state transitions all happen on
the main thread and nothing here needs a lock.
"""
from __future__ import annotations

import datetime
import threading
import time
import traceback
from collections import deque
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from . import client as client_mod
from . import commands, config, mods, tools
from .tools import policy
from .ui import theme
from .voice import attention as attention_mod
from .voice import audio, stt, tts


class State:
    OFFLINE = "offline"
    MUTED = "muted"
    LISTENING = "listening"
    HEARING = "hearing"
    THINKING = "thinking"
    TOOL = "tool"
    CONFIRM = "confirm"
    SPEAKING = "speaking"


class Bridge(QObject):
    """Signals emitted from worker threads, delivered on the main thread."""
    utterance = Signal(str)
    partial = Signal(str)
    level = Signal(float)
    wake_heard = Signal()
    turn_event = Signal(dict)
    tool_done = Signal(dict)
    speaking = Signal(bool)
    spoken = Signal(str)
    connected = Signal(dict)
    connect_failed = Signal(str)
    worker_error = Signal(str)
    stats = Signal(dict)
    sessions = Signal(list)
    history = Signal(list)
    logged_in = Signal(str)


class Controller(QObject):
    state_changed = Signal(str)
    level = Signal(float)                 # mic while listening, speaker while speaking
    partial_text = Signal(str)            # live transcript of what it hears
    user_message = Signal(str)
    assistant_delta = Signal(str)
    assistant_done = Signal(str, dict)
    spoken_sentence = Signal(str)
    status = Signal(str, str)             # key, text  (backend, agent, mic, stt, tts, mode)
    activity = Signal(dict)               # {kind, title, detail, ts}
    approval_needed = Signal(dict)
    approval_resolved = Signal()
    personas_loaded = Signal(list)
    persona_changed = Signal(str)
    error = Signal(str)
    ui_request = Signal(str, object)      # "chat"/"activity"/"settings"/"show" + value
    backend_health = Signal(dict)
    sessions_loaded = Signal(list)        # [{name, persona, updated}]
    history_loaded = Signal(list)         # [{role, content, ...}] oldest first
    account_changed = Signal(str)         # username or ""

    def __init__(self):
        super().__init__()
        self.state = State.OFFLINE
        self.client = client_mod.GenesisClient()
        self.bridge = Bridge()
        self.attention = attention_mod.Attention()
        self.personas: list[dict] = []
        self.persona = config.get("persona")
        self.muted = False
        self.health: dict = {}
        self.voice_cfg: dict = {}
        self.last_reply = ""
        self._reply = ""
        self._sentences = tts.SentenceBuffer()
        self._pending: list[dict] = []
        self._results: list[dict] = []
        self._current_approval: Optional[dict] = None
        self._turn_thread: Optional[threading.Thread] = None
        self._turn_gen = 0
        self._log_file = None

        self.capture = audio.Capture(config.get("sample_rate"), device=config.get("mic_device"))
        self.capture.on_chunk = self._on_chunk
        self.capture.on_error = lambda m: self.bridge.worker_error.emit(m)
        self.listener = Listener(self)
        self.speaker = tts.Speaker(self.client)
        self.speaker.on_level = lambda v: self.bridge.level.emit(v)
        self.speaker.on_speaking = lambda v: self.bridge.speaking.emit(v)
        self.speaker.on_sentence = lambda s: self.bridge.spoken.emit(s)
        self.speaker.on_error = lambda m: self.bridge.worker_error.emit(m)
        self.client_tools_support = None      # None: backend predates the protocol
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(2000)
        self._stats_timer.timeout.connect(self._poll_stats)
        self._stats_ok = True

        b = self.bridge
        b.utterance.connect(self._on_utterance, Qt.QueuedConnection)
        b.partial.connect(self._on_partial, Qt.QueuedConnection)
        b.level.connect(self._on_level, Qt.QueuedConnection)
        b.wake_heard.connect(self._on_wake_heard, Qt.QueuedConnection)
        b.turn_event.connect(self._on_turn_event, Qt.QueuedConnection)
        b.tool_done.connect(self._on_tool_done, Qt.QueuedConnection)
        b.speaking.connect(self._on_speaking, Qt.QueuedConnection)
        b.spoken.connect(self._on_spoken, Qt.QueuedConnection)
        b.connected.connect(self._on_connected, Qt.QueuedConnection)
        b.connect_failed.connect(self._on_connect_failed, Qt.QueuedConnection)
        b.worker_error.connect(self._on_worker_error, Qt.QueuedConnection)
        b.stats.connect(self._on_stats, Qt.QueuedConnection)
        b.sessions.connect(self.sessions_loaded, Qt.QueuedConnection)
        b.history.connect(self.history_loaded, Qt.QueuedConnection)
        b.logged_in.connect(self._on_logged_in, Qt.QueuedConnection)

        config.watch("*", self._on_config_changed)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self):
        config.ensure_dirs()
        tools.load_builtins()
        mods.install_example()
        mods.load_enabled()
        if config.get("transcript_log"):
            self._log_file = config.LOG_DIR / f"transcript-{datetime.date.today()}.log"
        self.status.emit("mode", self._mode_label())
        self.status.emit("agent", self.persona_display())
        self.connect()
        self.listener.start()
        self._start_mic()

    def shutdown(self):
        config.unwatch(self._on_config_changed)
        mods.run("shutdown")
        self.speaker.stop()
        self.capture.stop()
        self.listener.stop()

    def connect(self):
        self._set_state(State.OFFLINE)
        self.status.emit("backend", f"connecting to {self.client.base_url}…")
        threading.Thread(target=self._connect_worker, daemon=True, name="connect").start()

    def _connect_worker(self):
        try:
            health = self.client.health()
            try:
                personas = self.client.personas()
            except client_mod.BackendError as e:
                if config.get("account_token") and (" 401 " in str(e) or " 403 " in str(e)):
                    # the account session expired; fall back to the shared token
                    config.set("account_token", "")
                    self.bridge.worker_error.emit("your account login expired; using the shared token")
                    personas = self.client.personas()
                else:
                    raise
            try:
                vc = self.client.voice_config()
            except client_mod.BackendError:
                vc = {}
            self.bridge.connected.emit({"health": health, "personas": personas, "voice": vc})
        except client_mod.BackendError as e:
            self.bridge.connect_failed.emit(str(e))
        except Exception as e:
            self.bridge.connect_failed.emit(f"{e}")

    @Slot(dict)
    def _on_connected(self, info):
        self.health = info["health"]
        self.personas = info["personas"]
        self.voice_cfg = info["voice"]
        names = [p["name"] for p in self.personas]
        self.attention.set_personas(names, [p.get("title", "") for p in self.personas])
        theme.set_backend_accents({p["name"]: p.get("accent_color", "") for p in self.personas})
        for p in self.personas:
            tts.register_persona_voice(p["name"], p.get("voice", ""))
        if self.persona not in names and names:
            self.persona = names[0]
        self.client_tools_support = client_mod.GenesisClient.supports_client_tools(self.health)
        self.personas_loaded.emit(self.personas)
        self.backend_health.emit(self.health)
        h = self.health
        self.status.emit("backend", f"{h.get('provider', '?')} · {h.get('model', '?')}"
                         + ("" if h.get("ok") else " · model unreachable"))
        if self.client_tools_support is None:
            self.status.emit("tool", "backend has no client tools")
            self._log("system", "this backend predates client tools; local tools are unavailable to the model")
        elif not self.client_tools_support:
            self.status.emit("tool", "client tools off on backend")
        else:
            self.status.emit("tool", "")
        self.account_changed.emit(config.get("account_user") if config.get("account_token") else "")
        self.status.emit("agent", self.persona_display())
        self._configure_speech()
        self.refresh_sessions()
        self.load_history()
        self._set_state(State.MUTED if self.muted else State.LISTENING)
        self._log("system", f"connected to {self.client.base_url}")
        if config.get("greet_on_start") and not getattr(self, "_greeted", False):
            self._greeted = True
            g = self._persona_info().get("greeting") or "Ready."
            self.say(g)

    @Slot(str)
    def _on_connect_failed(self, msg):
        self.status.emit("backend", "offline")
        self.error.emit(msg)
        self._set_state(State.OFFLINE)
        self._log("error", msg)

    def _configure_speech(self):
        voice = self.persona_voice()
        eng, note = self.speaker.configure(voice, self.voice_cfg.get("tts_engine", "browser"))
        self.status.emit("tts", f"{eng} · {voice}" if eng else f"no speech: {note}")
        self.listener.reconfigure()

    # ------------------------------------------------------------------
    # accounts
    # ------------------------------------------------------------------
    def login(self, username: str, password: str):
        def worker():
            try:
                token, user = self.client.login(username, password)
                config.set("account_token", token, persist=False)
                config.set("account_user", user)
                config.set("account_token", token)
                config.set("user", user)
                self.bridge.logged_in.emit(user)
            except client_mod.BackendError as e:
                self.bridge.worker_error.emit(str(e))
        threading.Thread(target=worker, daemon=True, name="login").start()

    def logout(self):
        threading.Thread(target=self.client.logout, daemon=True).start()
        config.set("account_token", "")
        config.set("account_user", "")
        self.account_changed.emit("")
        self.connect()

    @Slot(str)
    def _on_logged_in(self, user):
        self._log("system", f"logged in as {user}")
        self.account_changed.emit(user)
        self.connect()

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    def refresh_sessions(self):
        def worker():
            try:
                self.bridge.sessions.emit(self.client.sessions(self.persona))
            except client_mod.BackendError:
                self.bridge.sessions.emit([])
        threading.Thread(target=worker, daemon=True).start()

    def load_history(self):
        if not config.get("load_history"):
            return
        persona = self.persona

        def worker():
            try:
                rows = self.client.history(persona, limit=60) or []
                self.bridge.history.emit(rows)
            except client_mod.BackendError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def set_session(self, name: str):
        name = (name or "").strip() or "default"
        if name == config.get("session"):
            return
        self.interrupt()
        config.set("session", name)
        self._log("system", f"conversation: {name}")
        self.load_history()
        self.refresh_sessions()

    def new_session(self):
        self.set_session(datetime.datetime.now().strftime("%Y-%m-%d %H.%M"))

    def delete_session(self, name: str):
        def worker():
            try:
                self.client.delete_session(self.persona, name)
            except client_mod.BackendError as e:
                self.bridge.worker_error.emit(str(e))
            self.bridge.sessions.emit(self.client.sessions(self.persona))
        threading.Thread(target=worker, daemon=True).start()
        if name == config.get("session"):
            config.set("session", "default")
            self.load_history()

    # ------------------------------------------------------------------
    # agent stats while a turn runs
    # ------------------------------------------------------------------
    def _poll_stats(self):
        if not (config.get("show_stats") and self._stats_ok and self.health):
            return

        def worker():
            try:
                self.bridge.stats.emit(self.client.agent_stats() or {})
            except client_mod.BackendError as e:
                if " 404 " in str(e):
                    self._stats_ok = False
        threading.Thread(target=worker, daemon=True).start()

    @Slot(dict)
    def _on_stats(self, d):
        parts = []
        mem = d.get("memory") or {}
        if isinstance(mem, dict) and mem.get("used_gb") is not None:
            parts.append(f"ram {mem.get('used_gb')}/{mem.get('total_gb')} GB")
        elif isinstance(mem, dict) and mem.get("percent") is not None:
            parts.append(f"ram {mem['percent']}%")
        gpu = d.get("gpu") or {}
        if isinstance(gpu, dict) and gpu.get("used_gb") is not None:
            parts.append(f"gpu {gpu.get('used_gb')}/{gpu.get('total_gb')} GB")
        elif isinstance(gpu, list) and gpu:
            g = gpu[0]
            if isinstance(g, dict) and g.get("used_gb") is not None:
                parts.append(f"gpu {g.get('used_gb')}/{g.get('total_gb')} GB")
        if parts:
            self.status.emit("stats", " · ".join(parts))

    def _start_mic(self):
        if config.get("voice_mode") == "off":
            self.capture.stop()
            self.status.emit("mic", "voice off")
            return
        if self.capture.start():
            self.status.emit("mic", "mic on" if not self.muted else "muted")
        else:
            self.status.emit("mic", self.capture.error or "no microphone")
            self.error.emit(self.capture.error or "no microphone")

    # ------------------------------------------------------------------
    # persona / settings
    # ------------------------------------------------------------------
    def _persona_info(self) -> dict:
        for p in self.personas:
            if p["name"] == self.persona:
                return p
        return {"name": self.persona, "title": self.persona.title()}

    def persona_voice(self) -> str:
        override = config.get("persona_voices").get(self.persona)
        return tts.resolve_voice(self._persona_info(), override)

    def persona_style(self) -> dict:
        p = self._persona_info()
        return {"pitch": p.get("voice_pitch") or 1.0, "rate": p.get("voice_rate") or 1.0,
                "gender": p.get("voice_gender") or "", "persona": self.persona}

    def persona_display(self, name=None) -> str:
        p = self._persona_info() if name in (None, self.persona) else \
            next((x for x in self.personas if x["name"] == name), {"name": name})
        title = p.get("title") or p["name"].title()
        avatar = p.get("avatar") or ""
        return f"{avatar} {title}".strip()

    def persona_aliases(self) -> dict:
        """spoken alias -> persona name, for the switch command."""
        out = {}
        for p in self.personas:
            out[p["name"].lower()] = p["name"]
            for a in attention_mod.title_aliases(p.get("title", "")):
                out.setdefault(a, p["name"])
        return out

    def set_persona(self, name: str, announce=True):
        names = [p["name"] for p in self.personas] or [name]
        if name not in names:
            self.error.emit(f"no persona {name!r}")
            return
        if name == self.persona:
            return
        self.interrupt()
        self.persona = name
        config.set("persona", name)
        self.status.emit("agent", self.persona_display())
        self.persona_changed.emit(name)
        self._configure_speech()
        self._log("system", f"switched to {name}")
        self.refresh_sessions()
        self.load_history()
        if announce:
            self.say(self._persona_info().get("greeting") or f"{name.title()} here.")

    def set_mode(self, mode: str):
        config.set("voice_mode", mode)

    def set_muted(self, muted: bool):
        self.muted = muted
        self.capture.paused = muted and not self.speaker.speaking
        self.status.emit("mic", "muted" if muted else "mic on")
        if muted:
            self.interrupt()
            self._set_state(State.MUTED)
        elif self.state == State.MUTED:
            self._set_state(State.LISTENING)

    def push_start(self):
        """Push-to-talk pressed."""
        self.attention.pushed = True
        if self.speaker.speaking:
            self.speaker.stop()
        if self.muted:
            self.set_muted(False)
        self.listener.force_open()
        self._set_state(State.HEARING)

    def push_end(self):
        self.attention.pushed = False
        self.listener.force_close()

    def _mode_label(self):
        return {"wake": "wake word", "push": "push to talk", "always": "always listening",
                "off": "voice off"}.get(config.get("voice_mode"), "?")

    def _on_config_changed(self, key, old, new):
        if key in ("voice_mode",):
            self.status.emit("mode", self._mode_label())
            self._start_mic()
            if new != "off" and self.state == State.OFFLINE and self.health:
                self._set_state(State.LISTENING)
        elif key in ("mic_device", "sample_rate"):
            self.capture.stop()
            self.capture.device = config.get("mic_device")
            self.capture.sample_rate = config.get("sample_rate")
            self.capture.chunk = int(self.capture.sample_rate / 10)
            self.listener.reconfigure()
            self._start_mic()
        elif key in ("stt_engine", "vosk_model", "whisper_model", "tts_engine",
                     "piper_voice_dir", "persona_voices", "output_device"):
            self._configure_speech()
        elif key in ("backend_url", "api_token", "admin_token"):
            self.connect()
        elif key == "persona" and new != self.persona:
            self.set_persona(new, announce=False)
        elif key == "enabled_mods":
            mods.reload_all()

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _set_state(self, s):
        if s == self.state:
            return
        self.state = s
        self.state_changed.emit(s)
        mods.run("on_state", s)
        busy = s in (State.THINKING, State.TOOL)
        if busy and not self._stats_timer.isActive():
            self._stats_timer.start()
            self._poll_stats()
        elif not busy and self._stats_timer.isActive():
            self._stats_timer.stop()

    def _idle_state(self):
        if not self.health:
            return State.OFFLINE
        if self.muted:
            return State.MUTED
        return State.LISTENING

    def _log(self, kind, text):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.activity.emit({"kind": kind, "title": text, "detail": "", "ts": ts})
        if self._log_file:
            try:
                with open(self._log_file, "a") as f:
                    f.write(f"{ts} [{kind}] {text}\n")
            except OSError:
                pass

    # ------------------------------------------------------------------
    # microphone -> listener -> utterance
    # ------------------------------------------------------------------
    def _on_chunk(self, pcm, level):
        self.listener.feed(pcm, level, self.state)

    @Slot(float)
    def _on_level(self, v):
        self.level.emit(v)

    @Slot(str)
    def _on_partial(self, text):
        self.partial_text.emit(text)
        if self.state == State.LISTENING and text and \
                (self.attention.window_open() or self.attention.mode == "always"):
            self._set_state(State.HEARING)

    @Slot()
    def _on_wake_heard(self):
        if self.state == State.SPEAKING and config.get("barge_in"):
            self.speaker.stop()
            self._log("system", "interrupted by voice")
        if self.state in (State.LISTENING, State.SPEAKING):
            self._set_state(State.HEARING)

    @Slot(str)
    def _on_utterance(self, text):
        text = text.strip()
        if not text:
            if self.state == State.HEARING:
                self._set_state(self._idle_state())
            return
        if self.state == State.CONFIRM and self._current_approval:
            ans = commands.confirm_answer(text)
            if ans is not None:
                self._log("heard", text)
                self.resolve_approval(ans["value"], ans.get("always", False))
                return
        addressed, clean, attention_only = self.attention.check(text)
        if self.state == State.SPEAKING:
            # something got through while speaking: only a wake word counts
            wake, _ = self.attention.find_wake(text)
            if not wake:
                return
            self.speaker.stop()
        if not addressed:
            self._log("heard", f"(not for me) {text}")
            self.partial_text.emit("")
            if self.state == State.HEARING:
                self._set_state(self._idle_state())
            return
        if attention_only:
            self.attention.arm(float(config.get("follow_up_seconds")) or 8.0)
            self._log("heard", text)
            self.say("Yes?")
            return
        self._log("heard", text)
        self.submit(clean, voice=True)

    # ------------------------------------------------------------------
    # a turn
    # ------------------------------------------------------------------
    def submit(self, text: str, voice=False):
        text = text.strip()
        if not text:
            return
        self.partial_text.emit("")
        self.user_message.emit(text)
        names = self.persona_aliases() or [self.persona]

        out = commands.match(text, names)
        if out and not (out.get("action") == "confirm"):
            self._log("command", text)
            self._do_command(out)
            return
        ctx = {"text": text, "persona": self.persona, "voice": voice}
        reply = mods.try_voice_command(text, ctx)
        if reply is None:
            ctx = mods.chain("before_send", ctx) or ctx
            reply = ctx.get("handled")
            text = ctx.get("text", text)
        if reply is not None:
            self._log("mod", f"{text} -> {reply[:80]}")
            self._finish_local_reply(str(reply))
            return
        if not self.health:
            self.error.emit("not connected to the backend")
            self.say("I can't reach the backend.")
            return
        self._begin_turn(text=text, voice=voice)

    def _finish_local_reply(self, reply):
        self.assistant_delta.emit(reply)
        self.assistant_done.emit(reply, {"local": True})
        self.last_reply = reply
        self.say(reply)

    def _do_command(self, out):
        act = out.get("action")
        if out.get("say"):
            self._finish_local_reply(out["say"])
        if act == "interrupt":
            self.interrupt()
        elif act == "persona":
            self.set_persona(out["name"], announce=not out.get("say"))
        elif act == "mute":
            self.set_muted(out["value"])
            if out["value"]:
                self.say("Muted. Click the microphone to wake me.")
        elif act in ("chat", "activity", "settings"):
            self.ui_request.emit(act, out.get("value", True))
        elif act == "repeat":
            self.say(self.last_reply or "I haven't said anything yet.")
        elif act == "clear_history":
            threading.Thread(target=self._clear_history, daemon=True).start()
        elif act == "rate":
            r = max(0.5, min(2.0, config.get("tts_rate") + out["delta"]))
            config.set("tts_rate", round(r, 2))
            self.say("Like this?")
        elif act == "volume":
            cur = tools.run("volume", {"action": "get"})
            self._log("tool", f"volume {cur.splitlines()[0] if cur else ''}")
            tools.run("run_command", {"command": f"pactl set-sink-volume @DEFAULT_SINK@ {'+' if out['delta'] > 0 else '-'}{abs(out['delta'])}%"})
            self.say("Done.")

    def _clear_history(self):
        try:
            self.client.clear_history(self.persona)
            self.say("History cleared.")
        except client_mod.BackendError as e:
            self.bridge.worker_error.emit(str(e))

    def _begin_turn(self, text="", tool_results=None, voice=True):
        self._turn_gen += 1
        gen = self._turn_gen
        if not tool_results:
            self._reply = ""
            self._sentences = tts.SentenceBuffer()
            self._results = []
        self._pending = []
        self._set_state(State.THINKING)
        specs = tools.specs()

        def worker():
            try:
                for ev in self.client.turn(self.persona, text, client_tools=specs,
                                           tool_results=tool_results, voice=voice):
                    if gen != self._turn_gen:
                        return
                    self.bridge.turn_event.emit(ev)
            except Exception as e:
                self.bridge.turn_event.emit({"type": "error", "message": f"{e}"})
                self.bridge.turn_event.emit({"type": "done", "text": "", "sources": [],
                                             "interrupted": False, "pending_tools": [], "failed": True})
        self._turn_thread = threading.Thread(target=worker, daemon=True, name="turn")
        self._turn_thread.start()

    @Slot(dict)
    def _on_turn_event(self, ev):
        t = ev.get("type")
        if t == "start":
            self.status.emit("backend", f"{self.health.get('provider', '?')} · {ev.get('model', '')}")
        elif t == "sources":
            self._log("sources", ", ".join(ev.get("sources", [])))
        elif t == "tool_start":
            self.status.emit("tool", f"backend: {ev.get('name')}")
            self._set_state(State.TOOL)
        elif t == "tool":
            if self.state == State.TOOL and not ev.get("client"):
                self._set_state(State.THINKING)
                self.status.emit("tool", "")
            where = "here" if ev.get("client") else "backend"
            self.activity.emit({"kind": "tool", "title": f"[{where}] {ev.get('name')}",
                                "detail": f"{ev.get('args')}\n{ev.get('result', '')}",
                                "ts": datetime.datetime.now().strftime("%H:%M:%S")})
        elif t == "tool_call":
            self._pending.append({"id": ev["id"], "name": ev["name"], "args": ev.get("args", {})})
        elif t == "delta":
            d = ev.get("text", "")
            self._reply += d
            self.assistant_delta.emit(d)
            for s in self._sentences.feed(d):
                self._speak_sentence(s)
        elif t == "error":
            self.error.emit(ev.get("message", "error"))
            self._log("error", ev.get("message", ""))
        elif t == "done":
            if ev.get("pending_tools"):
                self._pending = list(ev["pending_tools"])
                self._run_pending_tools()
                return
            for s in self._sentences.flush():
                self._speak_sentence(s)
            if ev.get("failed"):
                self.say("Sorry, that didn't work. Check the activity panel.")
            usage = ev.get("usage")
            if isinstance(usage, dict) and usage.get("total_tokens"):
                self.status.emit("stats", f"{usage.get('prompt_tokens', 0)} in · {usage.get('completion_tokens', 0)} out tokens")
            reply = self._reply
            self.last_reply = reply or self.last_reply
            self.assistant_done.emit(reply, ev)
            if reply:
                self._log("reply", reply[:200])
            mods.run("after_reply", {"persona": self.persona}, reply)
            if not self.speaker.speaking and self._idle_after_reply():
                self._after_reply()

    def _idle_after_reply(self):
        return not self.speaker.speaking

    def _after_reply(self):
        self.attention.note_reply_finished()
        self._set_state(self._idle_state())

    def _speak_sentence(self, s):
        if config.get("speak_replies") and self.speaker.engine:
            self.speaker.say_sentence(s, self.persona_voice(), self.persona_style())

    def say(self, text):
        self.spoken_sentence.emit(text)
        if config.get("speak_replies") and self.speaker.engine:
            self.speaker.say(text, self.persona_voice(), self.persona_style())
        else:
            self.attention.note_reply_finished()

    def interrupt(self):
        """Stop whatever is happening: the reply, the speech, a pending tool."""
        self._turn_gen += 1
        self.client.cancel()
        self.speaker.stop()
        if self._current_approval:
            self._current_approval = None
            self._pending = []
            self.approval_resolved.emit()
        if self._reply.strip():
            self.assistant_done.emit(self._reply, {"interrupted": True})
            self.last_reply = self._reply
        self._reply = ""
        self._set_state(self._idle_state())

    # ------------------------------------------------------------------
    # local tools
    # ------------------------------------------------------------------
    def _run_pending_tools(self):
        if not self._pending:
            self._set_state(State.THINKING)
            self._begin_turn(tool_results=self._results)
            return
        call = self._pending[0]
        tool = tools.get(call["name"])
        if not tool or not config.get("local_tools_enabled"):
            self._finish_tool(call, f"no such local tool: {call['name']}")
            return
        decision = policy.decide(tool, call["args"])
        risk = policy.classify(tool, call["args"])
        summary = tool.summary(call["args"])
        if decision == "refuse":
            self._log("refused", summary)
            self._finish_tool(call, f"refused by the desktop's tool policy ({config.get('tool_policy')}): {summary}")
            return
        if decision == "ask":
            self._current_approval = {**call, "summary": summary, "risk": risk,
                                      "tool": tool.name}
            self._set_state(State.CONFIRM)
            self.approval_needed.emit(self._current_approval)
            self._log("ask", summary)
            self.say(f"I'd like to run: {self._speakable(summary)}. Allow?")
            return
        self._execute(call, tool, summary)

    @staticmethod
    def _speakable(summary: str) -> str:
        s = summary.strip()
        if s.startswith(("$ ", "# ")):
            s = s[2:]
        return s[:160]

    def resolve_approval(self, allow: bool, always: bool = False):
        call = self._current_approval
        if not call:
            return
        self._current_approval = None
        self.approval_resolved.emit()
        tool = tools.get(call["tool"])
        if allow:
            if always:
                policy.remember_allow(tool, call["args"])
            self._log("allowed", call["summary"])
            self._execute(call, tool, call["summary"])
        else:
            self._log("denied", call["summary"])
            self._finish_tool(call, "the user declined to run this")

    def _execute(self, call, tool, summary):
        self._set_state(State.TOOL)
        self.status.emit("tool", summary[:60])
        if config.get("speak_tool_activity") and tool.name in ("packages", "service") or \
                (tool.name == "run_command" and call["args"].get("as_root")):
            self.say("Working on it.")

        def worker():
            t0 = time.time()
            try:
                result = tools.run(call["name"], call["args"])
            except Exception as e:
                result = f"{call['name']} crashed: {e}\n{traceback.format_exc(limit=2)}"
            self.bridge.tool_done.emit({"call": call, "result": result, "secs": time.time() - t0})
        threading.Thread(target=worker, daemon=True, name="tool").start()

    @Slot(dict)
    def _on_tool_done(self, info):
        call, result = info["call"], info["result"]
        self.activity.emit({"kind": "tool", "title": f"[here] {tools.get(call['name']).summary(call['args']) if tools.get(call['name']) else call['name']}  ({info['secs']:.1f}s)",
                            "detail": result, "ts": datetime.datetime.now().strftime("%H:%M:%S")})
        self._finish_tool(call, result)

    def _finish_tool(self, call, result):
        self._results.append({"id": call["id"], "name": call["name"], "result": result[:12000]})
        if self._pending and self._pending[0]["id"] == call["id"]:
            self._pending.pop(0)
        self.status.emit("tool", "")
        self._run_pending_tools()

    # ------------------------------------------------------------------
    # speech feedback
    # ------------------------------------------------------------------
    @Slot(bool)
    def _on_speaking(self, speaking):
        if speaking:
            self.capture.paused = not config.get("barge_in") or self.muted
            self._set_state(State.SPEAKING)
        else:
            self.capture.paused = self.muted
            self.level.emit(0.0)
            if self.state == State.SPEAKING:
                if self._turn_thread and self._turn_thread.is_alive():
                    self._set_state(State.THINKING)     # still streaming
                else:
                    self._after_reply()

    @Slot(str)
    def _on_spoken(self, s):
        self.spoken_sentence.emit(s)

    @Slot(str)
    def _on_worker_error(self, msg):
        self.error.emit(msg)
        self._log("error", msg)


# ----------------------------------------------------------------------
class Listener:
    """Consumes microphone chunks on its own thread: VAD, streaming
    recognition, end-of-utterance, optional re-transcription."""

    def __init__(self, ctl: Controller):
        self.ctl = ctl
        self._q: deque = deque()
        self._ev = threading.Event()
        self._stop = False
        self._thread = None
        self._rec = None
        self._finisher = None
        self.engine = None
        self._pre = deque(maxlen=6)        # ~600 ms before speech started
        self._buf = bytearray()
        self._in_utt = False
        self._last_voice = 0.0
        self._utt_start = 0.0
        self._forced = False
        self._reconf = True
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="listener")
        self._thread.start()

    def stop(self):
        self._stop = True
        self._ev.set()

    def reconfigure(self):
        self._reconf = True

    def force_open(self):
        self._forced = True

    def force_close(self):
        self._forced = False

    def feed(self, pcm, level, state):
        if state in (State.OFFLINE, State.MUTED):
            self.ctl.bridge.level.emit(level)
            return
        self._q.append((pcm, level, state))
        self._ev.set()

    def _apply_config(self):
        self._reconf = False
        eng, note = stt.pick_engine(self.ctl.client)
        self.engine = eng
        try:
            self._rec = stt.VoskRecognizer(config.get("sample_rate")) if stt.vosk_ready()[0] else None
        except Exception as e:
            self._rec = None
            note = f"vosk: {e}"
        try:
            self._finisher = stt.make_finisher(eng, self.ctl.client) if eng else None
        except Exception as e:
            self._finisher = None
            note = f"{eng}: {e}"
        if eng:
            label = eng if not (eng != "vosk" and self._rec) else f"vosk + {eng}"
            self.ctl.status.emit("stt", label)
        else:
            self.ctl.status.emit("stt", f"no speech recognition: {note}")

    def _loop(self):
        while not self._stop:
            self._ev.wait(0.2)
            self._ev.clear()
            if self._reconf:
                self._apply_config()
            while self._q and not self._stop:
                pcm, level, state = self._q.popleft()
                try:
                    self._process(pcm, level, state)
                except Exception as e:
                    self.ctl.bridge.worker_error.emit(f"listener: {e}")
            if self._in_utt and self._q.__len__() == 0:
                self._check_timeout()

    def _process(self, pcm, level, state):
        thr = float(config.get("vad_threshold"))
        now = time.monotonic()
        speaking_state = state == State.SPEAKING
        if not speaking_state:
            self.ctl.bridge.level.emit(level)
        voiced = level > thr or self._forced
        if not self._in_utt:
            self._pre.append(pcm)
            if voiced and (self._rec or self._finisher):
                self._in_utt = True
                self._utt_start = now
                self._last_voice = now
                self._buf = bytearray(b"".join(self._pre))
                if self._rec:
                    self._rec.reset()
                    text = self._rec.feed(bytes(self._buf))
                    self._partial(text, state)
            return
        self._buf.extend(pcm)
        if voiced:
            self._last_voice = now
        if self._rec:
            text = self._rec.feed(pcm)
            self._partial(text, state)
        self._check_timeout()

    def _partial(self, text, state):
        if not text:
            return
        if self.ctl.attention.heard_wake(text) and state in (State.LISTENING, State.SPEAKING):
            self.ctl.bridge.wake_heard.emit()
        self.ctl.bridge.partial.emit(text)

    def _check_timeout(self):
        if not self._in_utt:
            return
        now = time.monotonic()
        silence = (now - self._last_voice) * 1000 >= int(config.get("silence_ms"))
        too_long = now - self._utt_start >= int(config.get("max_utterance_s"))
        if (silence and not self._forced) or too_long:
            self._finish()

    def _finish(self):
        self._in_utt = False
        pcm = bytes(self._buf)
        self._buf = bytearray()
        text = self._rec.finish() if self._rec else ""
        if self._finisher and len(pcm) > config.get("sample_rate") * 2 * 0.4:
            try:
                better = self._finisher.transcribe(pcm, config.get("sample_rate"))
                if better:
                    text = better
            except Exception as e:
                self.ctl.bridge.worker_error.emit(f"transcribe: {e}")
        self.ctl.bridge.utterance.emit(text)
