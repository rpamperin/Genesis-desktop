"""Fast, no-hardware tests: settings layering, the tool policy, the
attention rules, SSE parsing, the client against the fake backend, local
mods, voice commands, sentence buffering."""
import os
import textwrap

import pytest

from genesis_desktop import client as client_mod
from genesis_desktop import commands, config, mods, tools
from genesis_desktop.tools import policy
from genesis_desktop.voice import attention, tts


# ----------------------------------------------------------------------
# config
# ----------------------------------------------------------------------
def test_layering_and_reset(clean_config):
    assert config.get("tool_policy") == "ask"
    config.set("tool_policy", "trusted")
    assert config.source("tool_policy") == "file"
    config.load(force=True)
    assert config.get("tool_policy") == "trusted"
    assert config.reset("tool_policy") == "ask"


def test_env_beats_file(clean_config):
    config.set("persona", "yui")
    os.environ["GENESIS_DESKTOP_PERSONA"] = "alfred"
    try:
        assert config.get("persona") == "alfred"
        assert config.source("persona") == "env"
    finally:
        del os.environ["GENESIS_DESKTOP_PERSONA"]


@pytest.mark.parametrize("key,bad", [
    ("voice_mode", "loud"), ("vad_threshold", 5), ("tool_policy", "yolo"),
    ("follow_up_seconds", -1), ("wake_words", 3),
])
def test_bad_values_rejected(clean_config, key, bad):
    with pytest.raises((ValueError, TypeError)):
        config.set(key, bad)


def test_coercion_and_watchers(clean_config):
    seen = []
    config.watch("barge_in", lambda k, o, n: seen.append((o, n)))
    config.set("barge_in", "false")
    assert config.get("barge_in") is False
    assert seen == [(True, False)]
    config.set("wake_words", "alfred, computer")
    assert config.get("wake_words") == ["alfred", "computer"]
    config.reset("barge_in")
    config.reset("wake_words")


# ----------------------------------------------------------------------
# tool policy
# ----------------------------------------------------------------------
@pytest.mark.parametrize("cmd,risk", [
    ("df -h", "safe"),
    ("ls -la | grep foo", "safe"),
    ("cat /var/log/syslog | tail -5", "safe"),
    ("systemctl status ssh", "safe"),
    ("systemctl restart ssh", "mutating"),
    ("journalctl -u ssh -n 20 && df", "safe"),
    ("rm -rf /tmp/x", "mutating"),
    ("echo hi > out.txt", "mutating"),
    ("echo $(whoami)", "mutating"),
    ("apt install vim", "mutating"),
    ("sudo apt update", "privileged"),
    ("pkexec systemctl restart nginx", "privileged"),
    ("ip a", "safe"),
    ("ip link set eth0 down", "mutating"),
    ("git status", "safe"),
    ("git push", "mutating"),
    ("some-unknown-binary --flag", "mutating"),
    ("FOO=1 env", "safe"),
    ("", "safe"),
])
def test_command_classification(cmd, risk):
    assert policy.classify_command(cmd) == risk


def test_policy_decisions(clean_config):
    tools.load_builtins()
    run = tools.get("run_command")
    assert policy.decide(run, {"command": "df -h"}) == "run"
    assert policy.decide(run, {"command": "rm x"}) == "ask"
    assert policy.decide(run, {"command": "df -h", "as_root": True}) == "ask"
    config.set("tool_policy", "safe")
    assert policy.decide(run, {"command": "rm x"}) == "refuse"
    config.set("tool_policy", "trusted")
    assert policy.decide(run, {"command": "rm x"}) == "run"
    config.set("tool_policy", "ask")
    policy.remember_allow(run, {"command": "rm x"})
    assert policy.decide(run, {"command": "rm x"}) == "run"
    assert policy.decide(run, {"command": "rm y"}) == "ask"
    config.set("allow_privileged", False)
    assert policy.decide(run, {"command": "sudo ls"}) == "refuse"
    config.reset("allow_privileged")
    config.reset("tool_always_allow")
    config.reset("tool_policy")


def test_per_call_risk_on_structured_tools():
    tools.load_builtins()
    svc = tools.get("service")
    assert policy.classify(svc, {"action": "status", "name": "ssh"}) == "safe"
    assert policy.classify(svc, {"action": "restart", "name": "ssh"}) == "privileged"
    assert policy.classify(svc, {"action": "restart", "name": "x", "user": True}) == "mutating"
    pk = tools.get("packages")
    assert policy.classify(pk, {"action": "search", "name": "vim"}) == "safe"
    assert policy.classify(pk, {"action": "install", "name": "vim"}) == "privileged"
    assert policy.classify(tools.get("read_file"), {"path": "/etc/passwd"}) == "safe"
    assert policy.classify(tools.get("write_file"), {"path": "x", "content": ""}) == "mutating"


def test_tools_run_and_specs(clean_config, tmp_path):
    tools.load_builtins()
    config.set("work_dir", str(tmp_path))
    assert "wrote" in tools.run("write_file", {"path": "a.txt", "content": "hello"})
    assert tools.run("read_file", {"path": "a.txt"}) == "hello"
    assert "wrote" in tools.run("write_file", {"path": "a.txt", "content": "again"})
    assert (tmp_path / "a.txt.bak").read_text() == "hello"
    assert "a.txt" in tools.run("list_directory", {})
    assert "hello" not in tools.run("run_command", {"command": "cat a.txt"})
    assert "again" in tools.run("run_command", {"command": "cat a.txt"})
    assert "no such local tool" in tools.run("nope", {})
    assert "bad arguments" in tools.run("read_file", {})
    names = {s["function"]["name"] for s in tools.specs()}
    assert {"run_command", "read_file", "service", "packages", "screenshot"} <= names
    config.set("local_tools_enabled", False)
    assert tools.specs() == []
    config.reset("local_tools_enabled")
    config.reset("work_dir")


# ----------------------------------------------------------------------
# attention
# ----------------------------------------------------------------------
def test_wake_word_rules(clean_config):
    a = attention.Attention(["alfred", "yui"])
    assert a.wake_words() == ["genesis", "alfred", "yui"]     # longest first
    assert a.check("Alfred, how full is the disk?") == (True, "how full is the disk", False)
    assert a.check("hey alfred what time is it") == (True, "what time is it", False)
    assert a.check("can you alfred check the fan") == (True, "can you check the fan", False)
    assert a.check("what time is it")[0] is False
    assert a.check("alfred") == (True, "", True)
    assert a.check("Yui, are you there?") == (True, "are you there", True)
    a.arm(5)
    assert a.check("what time is it") == (True, "what time is it", False)
    a.disarm()
    assert a.check("what time is it")[0] is False
    a.note_reply_finished()
    assert a.check("and the memory?")[0] is True
    assert a.heard_wake("hey alf") is False
    assert a.heard_wake("hey alfred can") is True


def test_modes(clean_config):
    a = attention.Attention(["alfred"])
    config.set("voice_mode", "off")
    assert a.check("alfred hi")[0] is False
    config.set("voice_mode", "push")
    assert a.check("just do it") == (True, "just do it", False)
    config.set("voice_mode", "always")
    assert a.check("just do it")[0] is False
    config.set("require_name_in_always", False)
    assert a.check("just do it")[0] is True
    config.set("voice_mode", "wake")
    config.set("wake_words", ["computer"])
    assert a.check("computer, lights")[0] is True
    assert a.check("alfred, lights")[0] is False
    for k in ("voice_mode", "require_name_in_always", "wake_words"):
        config.reset(k)


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("stop", {"action": "interrupt"}),
    ("never mind", {"action": "interrupt"}),
    ("switch to yui", {"action": "persona", "name": "yui"}),
    ("switch to nobody", None),
    ("show the chat", {"action": "chat", "value": True}),
    ("hide chat", {"action": "chat", "value": False}),
    ("open settings", {"action": "settings"}),
    ("mute", {"action": "mute", "value": True}),
    ("yes please", {"action": "confirm", "value": True}),
    ("no", {"action": "confirm", "value": False}),
    ("always allow", {"action": "confirm", "value": True, "always": True}),
    ("how full is the disk", None),
])
def test_builtin_commands(text, expect):
    assert commands.match(text, ["alfred", "yui"]) == expect


@pytest.mark.parametrize("text,expect", [
    ("no thanks", {"value": False}), ("yes go ahead", {"value": True}),
    ("yes, and always allow that", {"value": True, "always": True}),
    ("okay", {"value": True}), ("what does that do", None), ("no, never", {"value": False}),
])
def test_confirm_answers(text, expect):
    assert commands.confirm_answer(text) == expect


# ----------------------------------------------------------------------
# speech text
# ----------------------------------------------------------------------
def test_sentence_buffer_streams_sentences():
    b = tts.SentenceBuffer(min_chars=5)
    out = []
    for d in ["The disk ", "is 80% full. ", "Run apt clean", " to free space! Then", " check again."]:
        out += b.feed(d)
    out += b.flush()
    assert out == ["The disk is 80% full.", "Run apt clean to free space!", "Then check again."]


def test_code_blocks_wait_and_are_not_read():
    b = tts.SentenceBuffer(min_chars=5)
    out = b.feed("Try this. ```bash\nls -la. Done? no\n``` That lists files.")
    out += b.flush()
    assert out[0] == "Try this."
    joined = " ".join(out)
    assert "ls -la" not in joined and "code shown on screen" in joined
    assert out[-1] == "That lists files."


def test_clean_for_speech_strips_markdown():
    t = tts.clean_for_speech("## Title\n- **bold** item\n1. `code` and [link](http://x.y)\nhttps://example.com/x")
    assert t == "Title\nbold item\ncode and link\na link"


# ----------------------------------------------------------------------
# client
# ----------------------------------------------------------------------
def test_sse_parser_stops_on_done():
    lines = ['data: {"type": "start"}', "", "data: not json", 'data: {"type": "delta", "text": "x"}',
             "data: [DONE]", 'data: {"type": "never"}']
    assert [e["type"] for e in client_mod.parse_sse(lines)] == ["start", "delta"]


def test_client_round_trip(backend, clean_config):
    config.set("backend_url", backend, persist=False)
    config.set("api_token", "user-token", persist=False)
    config.set("admin_token", "admin-token", persist=False)
    c = client_mod.GenesisClient()
    assert c.health()["ok"] is True
    assert [p["name"] for p in c.personas()] == ["alfred", "yui"]
    events = list(c.turn("alfred", "hello"))
    assert events[0]["type"] == "start" and events[-1]["type"] == "done"
    assert "You said: hello" in events[-1]["text"]
    # client tools: the fake backend asks for df -h when offered run_command
    spec = {"type": "function", "function": {"name": "run_command", "parameters": {}}}
    events = list(c.turn("alfred", "disk?", client_tools=[spec]))
    pending = events[-1]["pending_tools"]
    assert pending == [{"id": "call-1", "name": "run_command", "args": {"command": "df -h"}}]
    events = list(c.turn("alfred", "", tool_results=[{"id": "call-1", "name": "run_command", "result": "12G"}]))
    assert "12G" in events[-1]["text"]
    # admin
    assert "temperature" in c.admin_settings()
    assert c.admin_set("temperature", 0.9)["value"] == 0.9
    with pytest.raises(client_mod.BackendError):
        c.admin_set("temperature", 9)


def test_client_auth_and_errors(backend, clean_config):
    config.set("backend_url", backend, persist=False)
    config.set("api_token", "wrong", persist=False)
    c = client_mod.GenesisClient()
    with pytest.raises(client_mod.BackendError):
        c.personas()
    events = list(c.turn("alfred", "hi"))
    assert events[0]["type"] == "error" and events[-1].get("failed")
    config.set("backend_url", "http://127.0.0.1:9", persist=False)
    events = list(client_mod.GenesisClient().turn("alfred", "hi"))
    assert events[-1].get("failed") and "connection failed" in events[0]["message"]


# ----------------------------------------------------------------------
# local mods
# ----------------------------------------------------------------------
def test_local_mod_lifecycle(clean_config):
    d = config.MODS_DIR / "hello"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mod.py").write_text(textwrap.dedent('''
        """Says hello."""
        from genesis_desktop import mods

        @mods.voice_command(r"say hello")
        def _hi(m, ctx):
            return "hello from the mod"

        @mods.tool({"type": "function", "function": {"name": "mod_tool", "parameters": {"type": "object", "properties": {}}}}, risk="safe")
        def mod_tool():
            return "mod result"

        @mods.hook("before_send")
        def _h(ctx):
            if ctx["text"] == "ping":
                ctx["handled"] = "pong"
            return ctx
    '''))
    broken = config.MODS_DIR / "broken"
    broken.mkdir(exist_ok=True)
    (broken / "mod.py").write_text("raise RuntimeError('boom')\n")

    names = {m["name"]: m for m in mods.discover()}
    assert names["hello"]["doc"] == "Says hello." and not names["hello"]["enabled"]
    ok, err = mods.enable("hello")
    assert ok and "hello" in config.get("enabled_mods")
    assert mods.try_voice_command("please say hello", {}) == "hello from the mod"
    assert tools.get("mod_tool").origin == "mod:hello"
    assert tools.run("mod_tool", {}) == "mod result"
    assert mods.chain("before_send", {"text": "ping"})["handled"] == "pong"

    ok, err = mods.enable("broken")
    assert not ok and "boom" in err
    assert mods.discover()[0]["error"]

    mods.disable("hello")
    assert mods.try_voice_command("say hello", {}) is None
    assert tools.get("mod_tool") is None
    mods.disable("broken")
    config.reset("enabled_mods")


def test_broken_hook_is_dropped_not_fatal():
    calls = []

    @mods.hook("after_reply")
    def bad(ctx, reply):
        calls.append(1)
        raise ValueError("nope")
    bad._mod = "test-bad"
    mods.run("after_reply", {}, "x")
    mods.run("after_reply", {}, "x")
    assert calls == [1]
    mods.HOOKS["after_reply"].remove(bad)
    mods._broken.discard("test-bad")
