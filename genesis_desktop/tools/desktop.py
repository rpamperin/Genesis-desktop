"""Desktop tools: notifications, opening things, clipboard, screenshots,
volume. The things a voice assistant on a desktop is actually asked for.
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from pathlib import Path

from .. import config
from . import register
from .system import _path, _run


@register({
    "type": "function",
    "function": {
        "name": "notify",
        "description": "Show a desktop notification.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            "required": ["title"],
        },
    },
}, risk="safe", describe=lambda a: f"notify: {a.get('title')}")
def notify(title: str, body: str = ""):
    if shutil.which("notify-send"):
        return _run(["notify-send", "-a", "Genesis", title, body])
    return "notify-send is not installed"


@register({
    "type": "function",
    "function": {
        "name": "open",
        "description": "Open a file, folder, URL or application with the desktop's default handler (xdg-open), or launch an app by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "path, URL, or app command such as 'firefox'"},
            },
            "required": ["target"],
        },
    },
}, risk="mutating", describe=lambda a: f"open {a.get('target')}")
def open(target: str):
    t = target.strip()
    if t.startswith(("http://", "https://", "mailto:", "file:")) or Path(os.path.expanduser(t)).exists():
        arg = t if "://" in t else str(_path(t))
        try:
            subprocess.Popen(["xdg-open", arg], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return f"opened {arg}"
        except FileNotFoundError:
            return "xdg-open is not installed"
    exe = t.split()[0]
    if shutil.which(exe):
        subprocess.Popen(t, shell=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return f"launched {t}"
    if shutil.which("gtk-launch"):
        r = subprocess.run(["gtk-launch", t], capture_output=True, text=True)
        if r.returncode == 0:
            return f"launched {t}"
    return f"could not find {t!r} as a file, URL or program"


@register({
    "type": "function",
    "function": {
        "name": "clipboard",
        "description": "Read or set the clipboard text.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set"]},
                "text": {"type": "string"},
            },
            "required": ["action"],
        },
    },
}, describe=lambda a: f"clipboard {a.get('action')}")
def clipboard(action: str, text: str = ""):
    try:
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard() if QApplication.instance() else None
    except Exception:
        cb = None
    if action == "get":
        if cb:
            return cb.text() or "(clipboard is empty)"
        if os.getenv("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
            return _run(["wl-paste", "-n"])
        if shutil.which("xclip"):
            return _run(["xclip", "-selection", "clipboard", "-o"])
        return "no clipboard tool available"
    if cb:
        cb.setText(text)
        return f"copied {len(text)} chars"
    if os.getenv("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text, text=True)
        return f"copied {len(text)} chars"
    if shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True)
        return f"copied {len(text)} chars"
    return "no clipboard tool available"


from . import REGISTRY as _R  # noqa: E402
_R["clipboard"].classify = lambda a: "safe" if a.get("action") == "get" else "mutating"


@register({
    "type": "function",
    "function": {
        "name": "screenshot",
        "description": "Take a screenshot of the whole screen and save it as a PNG. Returns the path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "where to save; default ~/Pictures"}},
        },
    },
}, risk="safe", describe=lambda a: "take a screenshot")
def screenshot(path: str = ""):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out = _path(path) if path else Path.home() / "Pictures" / f"screenshot-{stamp}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    tools = [
        (["gnome-screenshot", "-f", str(out)], "gnome-screenshot"),
        (["grim", str(out)], "grim"),
        (["spectacle", "-b", "-n", "-o", str(out)], "spectacle"),
        (["scrot", str(out)], "scrot"),
        (["import", "-window", "root", str(out)], "import"),
    ]
    for argv, exe in tools:
        if shutil.which(exe):
            _run(argv, timeout=20)
            if out.exists():
                return f"saved {out}"
    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen and screen.grabWindow(0).save(str(out)):
            return f"saved {out}"
    except Exception:
        pass
    return "no screenshot tool found (install gnome-screenshot, grim or scrot)"


@register({
    "type": "function",
    "function": {
        "name": "volume",
        "description": "Get or set the system output volume (0-100) or mute state.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set", "mute", "unmute"]},
                "level": {"type": "integer"},
            },
            "required": ["action"],
        },
    },
}, describe=lambda a: f"volume {a.get('action')} {a.get('level', '')}")
def volume(action: str, level: int = None):
    if not shutil.which("pactl"):
        return "pactl is not installed"
    if action == "get":
        return _run(["bash", "-c",
                     "pactl get-sink-volume @DEFAULT_SINK@ | head -1; pactl get-sink-mute @DEFAULT_SINK@"])
    if action == "set":
        lvl = max(0, min(100, int(level or 0)))
        return _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{lvl}%"]) + f"\nvolume {lvl}%"
    if action in ("mute", "unmute"):
        return _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@",
                     "1" if action == "mute" else "0"]) + f"\n{action}d"
    return f"unknown action {action}"


_R["volume"].classify = lambda a: "safe" if a.get("action") == "get" else "mutating"


@register({
    "type": "function",
    "function": {
        "name": "current_time",
        "description": "The current local date and time on the desktop.",
        "parameters": {"type": "object", "properties": {}},
    },
}, risk="safe", describe=lambda a: "current time")
def current_time():
    return datetime.datetime.now().strftime("%A %d %B %Y, %H:%M")


@register({
    "type": "function",
    "function": {
        "name": "user_directories",
        "description": "Where the user's Desktop, Documents, Downloads, Pictures folders are.",
        "parameters": {"type": "object", "properties": {}},
    },
}, risk="safe", describe=lambda a: "user folders")
def user_directories():
    names = ["DESKTOP", "DOCUMENTS", "DOWNLOAD", "PICTURES", "MUSIC", "VIDEOS"]
    out = []
    for n in names:
        if shutil.which("xdg-user-dir"):
            p = _run(["xdg-user-dir", n]).strip()
        else:
            p = str(Path.home() / n.title())
        out.append(f"{n.title()}: {p}")
    out.append(f"Work dir (relative paths resolve here): {config.work_dir()}")
    return "\n".join(out)
