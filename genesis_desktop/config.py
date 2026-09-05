"""Local settings for the desktop app.

These are about this machine: which backend to talk to, which microphone to
use, how tools are allowed to behave. Backend settings (model, provider,
RAG) live on the backend and are edited through its admin API; the settings
window shows both, on separate pages, so it is always clear which side a
knob belongs to.

Layering, lowest to highest: DEFAULTS -> settings.json -> environment
(GENESIS_DESKTOP_<KEY>). Same idea as the backend, on purpose.
"""
import json
import os
import threading
from pathlib import Path

APP_ID = "genesis-desktop"

CONFIG_DIR = Path(os.getenv("GENESIS_DESKTOP_CONFIG_DIR",
                            Path.home() / ".config" / APP_ID))
DATA_DIR = Path(os.getenv("GENESIS_DESKTOP_DATA_DIR",
                          Path.home() / ".local" / "share" / APP_ID))
SETTINGS_FILE = CONFIG_DIR / "settings.json"
MODS_DIR = CONFIG_DIR / "mods"
MODELS_DIR = DATA_DIR / "models"
LOG_DIR = DATA_DIR / "logs"

DEFAULTS = {
    # --- backend -----------------------------------------------------
    "backend_url": "http://127.0.0.1:8080",
    "api_token": "",
    "admin_token": "",
    "account_user": "",               # optional per-account login (POST /auth/login)
    "account_token": "",              # its session token; beats api_token when set
    "connect_timeout": 5,
    "autostart_backend": False,       # run the backend from this app
    "backend_command": "python -m genesis serve",
    "backend_dir": "",                # folder that holds the Genesis checkout

    # --- who you are talking to --------------------------------------
    "persona": "alfred",
    "session": "desktop",
    "user": "local",
    "greet_on_start": True,

    # --- attention: when is the user talking to it -------------------
    "voice_mode": "wake",             # wake | push | always | off
    "wake_words": [],                 # empty -> persona names + "genesis"
    "follow_up_seconds": 8.0,         # after a reply, no wake word needed
    "require_name_in_always": True,   # always mode: only answer when named
    "barge_in": True,                 # talking over the reply stops it

    # --- speech to text -----------------------------------------------
    "stt_engine": "auto",             # auto | vosk | whisper | backend
    "vosk_model": "",                 # folder; empty -> models/vosk-small
    "whisper_model": "base.en",
    "mic_device": "",                 # "" -> system default
    "sample_rate": 16000,
    "vad_threshold": 0.015,           # rms 0..1 that counts as speech
    "silence_ms": 900,                # end of utterance
    "max_utterance_s": 20,

    # --- text to speech -----------------------------------------------
    "tts_engine": "auto",             # auto | piper | backend | espeak | qt | off
    "speak_replies": True,
    "tts_rate": 1.0,
    "output_device": "",
    "piper_voice_dir": "",            # empty -> models/piper
    "persona_voices": {},             # persona -> piper voice name override
    "speak_tool_activity": True,      # "checking the disk..."

    # --- local tools ----------------------------------------------------
    "local_tools_enabled": True,
    "tool_policy": "ask",             # safe | ask | trusted
    "tool_always_allow": [],          # remembered "always allow" commands
    "tool_timeout": 60,
    "work_dir": "",                   # "" -> home directory
    "allow_privileged": True,         # pkexec for root actions, still asks

    # --- local mods -----------------------------------------------------
    "enabled_mods": [],

    # --- appearance -----------------------------------------------------
    "theme": "dark",                  # dark | light
    "visual_style": "orb",            # orb | bars | ring
    "show_chat": False,
    "show_activity": True,
    "start_in_tray": False,
    "always_on_top": False,
    "window_opacity": 1.0,
    "transcript_log": True,
    "show_stats": True,               # RAM/GPU/tokens pill while a turn runs
    "load_history": True,             # fill the chat panel from the backend's history
}

SCHEMA = {
    "backend_url":        {"type": str},
    "api_token":          {"type": str, "secret": True},
    "admin_token":        {"type": str, "secret": True},
    "account_user":       {"type": str},
    "account_token":      {"type": str, "secret": True},
    "connect_timeout":    {"type": int, "min": 1, "max": 60},
    "autostart_backend":  {"type": bool},
    "backend_command":    {"type": str},
    "backend_dir":        {"type": str},
    "persona":            {"type": str},
    "session":            {"type": str},
    "user":               {"type": str},
    "greet_on_start":     {"type": bool},
    "voice_mode":         {"type": str, "choices": ["wake", "push", "always", "off"]},
    "wake_words":         {"type": list},
    "follow_up_seconds":  {"type": float, "min": 0.0, "max": 120.0},
    "require_name_in_always": {"type": bool},
    "barge_in":           {"type": bool},
    "stt_engine":         {"type": str, "choices": ["auto", "vosk", "whisper", "backend"]},
    "vosk_model":         {"type": str},
    "whisper_model":      {"type": str},
    "mic_device":         {"type": str},
    "sample_rate":        {"type": int, "min": 8000, "max": 48000},
    "vad_threshold":      {"type": float, "min": 0.001, "max": 0.5},
    "silence_ms":         {"type": int, "min": 200, "max": 5000},
    "max_utterance_s":    {"type": int, "min": 3, "max": 120},
    "tts_engine":         {"type": str, "choices": ["auto", "piper", "backend", "espeak", "qt", "off"]},
    "speak_replies":      {"type": bool},
    "tts_rate":           {"type": float, "min": 0.5, "max": 2.0},
    "output_device":      {"type": str},
    "piper_voice_dir":    {"type": str},
    "persona_voices":     {"type": dict},
    "speak_tool_activity": {"type": bool},
    "local_tools_enabled": {"type": bool},
    "tool_policy":        {"type": str, "choices": ["safe", "ask", "trusted"]},
    "tool_always_allow":  {"type": list},
    "tool_timeout":       {"type": int, "min": 1, "max": 600},
    "work_dir":           {"type": str},
    "allow_privileged":   {"type": bool},
    "enabled_mods":       {"type": list},
    "theme":              {"type": str, "choices": ["dark", "light"]},
    "visual_style":       {"type": str, "choices": ["orb", "bars", "ring"]},
    "show_chat":          {"type": bool},
    "show_activity":      {"type": bool},
    "start_in_tray":      {"type": bool},
    "always_on_top":      {"type": bool},
    "window_opacity":     {"type": float, "min": 0.3, "max": 1.0},
    "transcript_log":     {"type": bool},
    "show_stats":         {"type": bool},
    "load_history":       {"type": bool},
}

_lock = threading.RLock()
_file_layer = {}
_loaded = False
_watchers = {}     # key -> [fn(key, old, new)]; "*" for every key


def _coerce(key, value):
    spec = SCHEMA.get(key)
    if not spec:
        return value
    want = spec["type"]
    if want is bool and isinstance(value, str):
        value = value.strip().lower() in ("1", "true", "yes", "on")
    elif want is list and isinstance(value, str):
        value = [p.strip() for p in value.split(",") if p.strip()]
    elif want is dict and isinstance(value, str):
        value = json.loads(value or "{}")
    elif want in (int, float) and isinstance(value, str):
        value = want(value)
    elif want is str:
        value = "" if value is None else str(value)
    if want in (int, float):
        value = want(value)
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and value < lo:
            raise ValueError(f"{key}: {value} below minimum {lo}")
        if hi is not None and value > hi:
            raise ValueError(f"{key}: {value} above maximum {hi}")
    if want is list and not isinstance(value, list):
        raise ValueError(f"{key}: expected a list")
    if want is dict and not isinstance(value, dict):
        raise ValueError(f"{key}: expected a mapping")
    choices = spec.get("choices")
    if choices and value not in choices:
        raise ValueError(f"{key}: must be one of {choices}, got {value!r}")
    return value


def _env_name(key):
    return "GENESIS_DESKTOP_" + key.upper()


def ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, MODS_DIR, MODELS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load(force=False):
    global _file_layer, _loaded
    with _lock:
        if _loaded and not force:
            return _file_layer
        _file_layer = {}
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text())
            except json.JSONDecodeError:
                raw = {}
            for k, v in raw.items():
                try:
                    _file_layer[k] = _coerce(k, v)
                except (ValueError, TypeError):
                    pass          # a bad saved value must not stop startup
        _loaded = True
        return _file_layer


def save():
    with _lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_file_layer, indent=2, sort_keys=True))
        tmp.replace(SETTINGS_FILE)


def get(key, default=None):
    load()
    env = os.getenv(_env_name(key))
    if env is not None:
        try:
            return _coerce(key, env)
        except (ValueError, TypeError):
            pass
    if key in _file_layer:
        return _file_layer[key]
    return DEFAULTS.get(key, default)


def all():
    load()
    out = dict(DEFAULTS)
    out.update(_file_layer)
    for key in list(out):
        env = os.getenv(_env_name(key))
        if env is not None:
            try:
                out[key] = _coerce(key, env)
            except (ValueError, TypeError):
                pass
    return out


def source(key):
    load()
    if os.getenv(_env_name(key)) is not None:
        return "env"
    if key in _file_layer:
        return "file"
    return "default"


def set(key, value, persist=True):
    with _lock:
        load()
        value = _coerce(key, value)
        old = get(key)
        _file_layer[key] = value
        if persist:
            save()
    _notify(key, old, value)
    return value


def reset(key):
    with _lock:
        load()
        old = get(key)
        _file_layer.pop(key, None)
        save()
    new = get(key)
    _notify(key, old, new)
    return new


def watch(key, fn):
    _watchers.setdefault(key, []).append(fn)
    return fn


def unwatch(fn):
    for fns in _watchers.values():
        while fn in fns:
            fns.remove(fn)


def _notify(key, old, new):
    if old == new:
        return
    for fn in _watchers.get(key, []) + _watchers.get("*", []):
        try:
            fn(key, old, new)
        except Exception as e:       # a watcher must not break a save
            print(f"[config] watcher for {key} raised: {e}")


def work_dir() -> Path:
    return Path(get("work_dir") or Path.home()).expanduser()


def vosk_model_dir() -> Path:
    return Path(get("vosk_model") or MODELS_DIR / "vosk").expanduser()


def piper_voice_dir() -> Path:
    return Path(get("piper_voice_dir") or MODELS_DIR / "piper").expanduser()
