"""What is missing. Same idea as the backend's `python -m genesis doctor`."""
from __future__ import annotations

import os
import shutil
import sys

from . import __version__, config
from .voice import audio, stt, tts


def report(ctl=None) -> str:
    lines = [f"genesis-desktop {__version__}  python {sys.version.split()[0]}",
             f"config: {config.SETTINGS_FILE}", f"data:   {config.DATA_DIR}", ""]

    def row(ok, label, detail=""):
        lines.append(f"  {'✓' if ok else '✗'} {label:<24} {detail}")

    lines.append("backend")
    if ctl and ctl.health:
        h = ctl.health
        row(True, "connection", f"{ctl.client.base_url}")
        row(bool(h.get("ok")), "model", f"{h.get('provider')} / {h.get('model')}: {h.get('detail', '')}")
        row(True, "personas", ", ".join(h.get("personas", [])))
        ct = ctl.client_tools_support
        row(ct is True, "client tools", "supported" if ct else (
            "switched off on the backend (client_tools_enabled)" if ct is False
            else "backend predates the client-tools protocol; Alfred cannot use this machine"))
        if config.get("account_token"):
            row(True, "account", config.get("account_user"))
        row(True, "auth", f"chat {'on' if h.get('chat_auth') else 'off'}, admin {'on' if h.get('admin_auth') else 'off'}")
        row(True, "backend voice", f"stt {ctl.voice_cfg.get('stt_engine', '?')}, tts {ctl.voice_cfg.get('tts_engine', '?')}")
    else:
        row(False, "connection", config.get("backend_url"))
    lines.append("")

    lines.append("audio")
    row(audio.available(), "PortAudio", audio.SD_ERROR or "sounddevice ok")
    mics = audio.input_devices()
    row(bool(mics), "microphones", ", ".join(n for _, n in mics)[:120] or "none found")
    outs = audio.output_devices()
    row(bool(outs), "outputs", ", ".join(n for _, n in outs)[:120] or "none found")
    row(bool(shutil.which("paplay") or shutil.which("aplay")), "fallback player", shutil.which("paplay") or shutil.which("aplay") or "install pulseaudio-utils")
    lines.append("")

    lines.append("speech to text")
    ok, msg = stt.vosk_ready()
    row(ok, "vosk", msg)
    ok, msg = stt.whisper_ready()
    row(ok, "faster-whisper", msg)
    lines.append("")

    lines.append("text to speech")
    voice = ctl.persona_voice() if ctl else "en_GB-alan-medium"
    ok, msg = tts.piper_ready(voice)
    row(ok, f"piper ({voice})", msg)
    ok, msg = tts.espeak_ready()
    row(ok, "espeak-ng", msg)
    ok, msg = tts.qt_ready()
    row(ok, "Qt speech", msg)
    if ctl:
        row(bool(ctl.speaker.engine), "in use", f"{ctl.speaker.engine} ({ctl.speaker.engine_note})")
    lines.append("")

    lines.append("desktop")
    row(bool(shutil.which("pkexec")), "pkexec", "root actions" if shutil.which("pkexec") else "install policykit-1")
    row(bool(shutil.which("notify-send")), "notify-send", "" if shutil.which("notify-send") else "install libnotify-bin")
    row(bool(shutil.which("xdg-open")), "xdg-open", "")
    row(bool(shutil.which("pactl")), "pactl", "volume control")
    ss = next((t for t in ("gnome-screenshot", "grim", "spectacle", "scrot") if shutil.which(t)), None)
    row(bool(ss), "screenshot", ss or "install gnome-screenshot or grim")
    row(True, "session", f"{os.getenv('XDG_SESSION_TYPE', '?')} / {os.getenv('XDG_CURRENT_DESKTOP', '?')}")
    lines.append("")
    lines.append("local mods")
    from . import mods
    for m in mods.discover():
        row(m["loaded"] or not m["enabled"], m["name"], "loaded" if m["loaded"] else ("off" if not m["enabled"] else (m["error"] or "").splitlines()[-1] if m["error"] else ""))
    return "\n".join(lines)
