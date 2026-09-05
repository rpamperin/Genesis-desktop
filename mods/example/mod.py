"""Example local mod -- copy this folder to start your own.

A local mod lives in ~/.config/genesis-desktop/mods/<name>/mod.py and runs
inside the desktop app, on this machine. It never touches the backend.
Enable it in Settings > Local mods.
"""
import datetime
import subprocess

from genesis_desktop import mods


# 1. runs once after the window exists. `app` is the Application object:
#    app.controller (state machine), app.window (main window), app.client.
@mods.hook("startup")
def _boot(app):
    print("[example mod] loaded")


# 2. a spoken phrase handled locally, before anything reaches the backend.
#    Return the text to speak back, or None to let the model handle it.
@mods.voice_command(r"\b(what|which) (day|date) is it\b")
def _today(match, ctx):
    return datetime.date.today().strftime("It's %A the %d of %B.")


# 3. a tool the model can call. It runs here. risk="safe" means it never
#    asks for approval; "mutating" asks under the default policy.
@mods.tool({
    "type": "function",
    "function": {
        "name": "battery",
        "description": "Battery charge and state on this laptop, if it has one.",
        "parameters": {"type": "object", "properties": {}},
    },
}, risk="safe", describe=lambda a: "check battery")
def battery():
    try:
        out = subprocess.run(
            ["bash", "-c", "cat /sys/class/power_supply/BAT*/capacity /sys/class/power_supply/BAT*/status"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
        if len(out) >= 2:
            return f"{out[0]}% ({out[1]})"
    except Exception:
        pass
    return "no battery found"


# 4. see every outgoing turn. Edit ctx["text"], or set ctx["handled"] to a
#    reply string to answer without calling the model at all.
@mods.hook("before_send")
def _stamp(ctx):
    if ctx["text"].strip().lower() in ("ping",):
        ctx["handled"] = "pong"
    return ctx


# 5. see every finished reply
@mods.hook("after_reply")
def _log(ctx, reply):
    pass
