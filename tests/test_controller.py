"""The state machine, driven headless against the fake backend."""
import time

import pytest

from genesis_desktop import config


@pytest.fixture
def app(backend, clean_config):
    from PySide6.QtWidgets import QApplication
    config.set("backend_url", backend, persist=False)
    config.set("api_token", "user-token", persist=False)
    config.set("admin_token", "admin-token", persist=False)
    config.set("greet_on_start", False, persist=False)
    config.set("tts_engine", "off", persist=False)
    config.set("voice_mode", "wake", persist=False)
    qt = QApplication.instance() or QApplication([])
    from genesis_desktop.controller import Controller
    ctl = Controller()
    ctl.errors = []
    ctl.error.connect(ctl.errors.append)
    ctl.start()
    wait_for(qt, lambda: bool(ctl.health) or any("reach" in e for e in ctl.errors), 8)
    assert ctl.health, ctl.errors
    yield qt, ctl
    ctl.shutdown()


def pump(qt, ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        qt.processEvents()
        time.sleep(0.005)


def wait_for(qt, pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qt.processEvents()
        if pred():
            return True
        time.sleep(0.005)
    return False


def test_plain_turn_and_states(app):
    qt, ctl = app
    states = []
    ctl.state_changed.connect(states.append)
    assert ctl.state == "listening"
    ctl.submit("hello", voice=False)
    assert wait_for(qt, lambda: "hello" in ctl.last_reply)
    assert states[0] == "thinking" and ctl.state == "listening"
    assert ctl.attention.window_open()


def test_safe_tool_runs_without_asking(app):
    qt, ctl = app
    asked = []
    ctl.approval_needed.connect(asked.append)
    ctl.submit("check the disk", voice=False)
    assert wait_for(qt, lambda: "The tool said" in ctl.last_reply, 5)
    assert asked == []
    assert "Filesystem" in ctl.last_reply or "tmpfs" in ctl.last_reply or "/" in ctl.last_reply


def test_mutating_tool_asks_and_voice_can_answer(app):
    qt, ctl = app
    asked = []
    ctl.approval_needed.connect(asked.append)
    ctl.submit("delete the temp thing", voice=False)
    assert wait_for(qt, lambda: ctl.state == "confirm")
    assert asked[0]["summary"] == "$ rm -rf /tmp/genesis-x" and asked[0]["risk"] == "mutating"
    ctl.bridge.utterance.emit("no thanks")
    assert wait_for(qt, lambda: "declined" in ctl.last_reply, 5)
    assert ctl.state == "listening"


def test_always_allow_is_remembered(app):
    qt, ctl = app
    ctl.submit("delete it", voice=False)
    assert wait_for(qt, lambda: ctl.state == "confirm")
    ctl.resolve_approval(True, always=True)
    assert wait_for(qt, lambda: ctl.state == "listening" and "The tool said" in ctl.last_reply, 5)
    assert "rm -rf /tmp/genesis-x" in config.get("tool_always_allow")
    ctl.submit("delete it again", voice=False)
    assert wait_for(qt, lambda: "The tool said" in ctl.last_reply and ctl.state == "listening", 5)
    config.reset("tool_always_allow")


def test_safe_policy_refuses_mutations(app):
    qt, ctl = app
    config.set("tool_policy", "safe", persist=False)
    ctl.submit("delete it", voice=False)
    assert wait_for(qt, lambda: "refused" in ctl.last_reply, 5)
    config.reset("tool_policy")


def test_error_event_returns_to_listening(app):
    qt, ctl = app
    ctl.submit("please fail", voice=False)
    assert wait_for(qt, lambda: any("model exploded" in e for e in ctl.errors))
    assert wait_for(qt, lambda: ctl.state == "listening")


def test_voice_commands_and_attention(app):
    qt, ctl = app
    ui = []
    ctl.ui_request.connect(lambda w, v: ui.append((w, v)))
    ctl.submit("switch to yui", voice=True)
    assert ctl.persona == "yui" and config.get("persona") == "yui"
    ctl.submit("show the chat", voice=True)
    assert ("chat", True) in ui
    ctl.attention.disarm()                              # the greeting opened a follow-up window
    ctl.bridge.utterance.emit("what is the time")      # no wake word
    pump(qt, 100)
    assert "time" not in ctl.last_reply
    ctl.bridge.utterance.emit("yui")                    # attention call
    pump(qt, 100)
    assert ctl.attention.window_open()
    ctl.bridge.utterance.emit("what is the time")
    assert wait_for(qt, lambda: "what is the time" in ctl.last_reply)
    ctl.bridge.utterance.emit("alfred, stop")
    pump(qt, 100)
    assert ctl.state == "listening"


def test_mute_and_interrupt(app):
    qt, ctl = app
    ctl.set_muted(True)
    assert ctl.state == "muted" and ctl.capture.paused
    ctl.set_muted(False)
    assert ctl.state == "listening"
    ctl.submit("hello", voice=False)
    ctl.interrupt()
    assert ctl.state == "listening"
    pump(qt, 500)
    assert ctl.state == "listening"


def test_mod_answers_before_backend(app):
    qt, ctl = app
    from genesis_desktop import mods
    mods.install_example()
    mods.enable("example")
    ctl.submit("ping", voice=False)
    pump(qt, 200)
    assert ctl.last_reply == "pong"
    mods.disable("example")


def test_house_persona_display_voice_and_switch(app):
    qt, ctl = app
    assert [p["name"] for p in ctl.personas] == ["alfred", "yui", "house"]
    assert ctl.persona_display("house") == "🩺 Dr. House"
    assert ctl.client_tools_support is True
    ctl.submit("switch to doctor house", voice=True)
    assert ctl.persona == "house"
    assert ctl.persona_style()["gender"] == "male" and ctl.persona_style()["pitch"] == 0.85
    assert ctl.persona_voice() == "en_GB-alan-medium"     # male default, not the backend's Amy
    from genesis_desktop.ui import theme
    assert theme.accent_for("house").lightnessF() >= 0.55


def test_backend_tool_start_and_usage(app):
    qt, ctl = app
    states, stats = [], []
    ctl.state_changed.connect(states.append)
    ctl.status.connect(lambda k, v: stats.append(v) if k == "stats" else None)
    ctl.submit("what's the weather", voice=False)
    assert wait_for(qt, lambda: "sunny" in ctl.last_reply)
    assert "tool" in states and ctl.state == "listening"
    assert any("tokens" in s for s in stats)


def test_login_and_history_and_sessions(app):
    qt, ctl = app
    users, hist, sess = [], [], []
    ctl.account_changed.connect(users.append)
    ctl.history_loaded.connect(hist.append)
    ctl.sessions_loaded.connect(sess.append)
    ctl.login("ray", "secret")
    assert wait_for(qt, lambda: "ray" in users and ctl.health and config.get("user") == "ray")
    ctl.submit("hello", voice=False)
    assert wait_for(qt, lambda: "hello" in ctl.last_reply)
    ctl.set_session("second")
    assert wait_for(qt, lambda: hist and hist[-1] == [])
    ctl.set_session("desktop")
    assert wait_for(qt, lambda: hist and [t["role"] for t in hist[-1]] == ["user", "assistant"])
    assert wait_for(qt, lambda: sess and "desktop" in [r["name"] for r in sess[-1]])
    ctl.logout()
    assert wait_for(qt, lambda: users[-1] == "" and not config.get("account_token"))
    config.reset("user")
    config.reset("session")
