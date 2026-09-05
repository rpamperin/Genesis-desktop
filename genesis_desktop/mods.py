"""Local mods: drop-in extensions that live on this machine only.

    ~/.config/genesis-desktop/mods/<name>/mod.py

They are separate from backend mods. A backend mod changes what the model
sees; a local mod changes what this program does: it can add tools that
run here, voice commands handled before anything is sent to the backend,
and hooks around the turn. Enable them in Settings > Local mods.

A mod that raises while loading is marked broken and skipped; a hook that
raises is dropped for the rest of the run. An add-on must not take the
assistant down.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import traceback
from pathlib import Path

from . import config, tools

HOOK_NAMES = (
    "startup",          # (app)                 once, after the UI exists
    "before_send",      # (ctx) -> ctx          ctx: {text, persona, voice}; may edit or set ctx["handled"]=reply
    "after_reply",      # (ctx, reply)          after the full reply arrived
    "on_state",         # (state)               listening/thinking/speaking...
    "shutdown",         # ()
)

HOOKS = {n: [] for n in HOOK_NAMES}
COMMANDS = []      # (pattern:re.Pattern, fn(match, ctx) -> str|None, origin)
LOADED = {}        # name -> {"ok": bool, "error": str|None}
_broken = set()
_current = None    # name of the mod being imported


# ----------------------------------------------------------------------
# decorators used inside a mod
# ----------------------------------------------------------------------
def hook(name):
    if name not in HOOKS:
        raise ValueError(f"unknown hook {name!r}; have {list(HOOKS)}")

    def deco(fn):
        fn._mod = _current or fn.__module__
        HOOKS[name].append(fn)
        return fn
    return deco


def tool(spec, risk=None, describe=None):
    """Register a tool that runs on this machine. Same spec format as the
    backend: an openai function spec. risk: 'safe' | 'mutating' | 'privileged'."""
    def deco(fn):
        tools.register(spec, fn, origin=f"mod:{_current or fn.__module__}",
                       risk=risk, describe=describe)
        return fn
    return deco


def voice_command(pattern, flags=re.IGNORECASE):
    """Handle a spoken phrase locally. The function gets the regex match and
    a ctx dict and returns what to say back (or None to fall through)."""
    rx = re.compile(pattern, flags)

    def deco(fn):
        COMMANDS.append((rx, fn, _current or fn.__module__))
        return fn
    return deco


# ----------------------------------------------------------------------
# discovery and loading
# ----------------------------------------------------------------------
def discover():
    root = config.MODS_DIR
    if not root.exists():
        return []
    enabled = set(config.get("enabled_mods"))
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        if not (d / "mod.py").exists():
            continue
        info = LOADED.get(d.name, {})
        out.append({
            "name": d.name,
            "path": str(d),
            "enabled": d.name in enabled,
            "loaded": bool(info.get("ok")),
            "error": info.get("error"),
            "doc": _docstring(d / "mod.py"),
        })
    return out


def _docstring(path: Path):
    try:
        head = path.read_text(errors="ignore")[:600].lstrip()
        if head.startswith(('"""', "'''")):
            q = head[:3]
            return head[3:].split(q)[0].strip().split("\n")[0]
    except Exception:
        pass
    return ""


def load(name):
    global _current
    path = config.MODS_DIR / name / "mod.py"
    if not path.exists():
        LOADED[name] = {"ok": False, "error": f"no mod.py in {path.parent}"}
        return False, LOADED[name]["error"]
    _current = name
    try:
        modname = f"genesis_desktop_mod_{name}"
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[modname] = module
        spec.loader.exec_module(module)
        LOADED[name] = {"ok": True, "error": None}
        return True, None
    except Exception:
        err = traceback.format_exc(limit=3)
        _unload(name)
        LOADED[name] = {"ok": False, "error": err}
        return False, err
    finally:
        _current = None


def _unload(name):
    for hooks in HOOKS.values():
        hooks[:] = [f for f in hooks if getattr(f, "_mod", None) != name]
    COMMANDS[:] = [c for c in COMMANDS if c[2] != name]
    tools.unregister_origin(f"mod:{name}")
    sys.modules.pop(f"genesis_desktop_mod_{name}", None)
    LOADED.pop(name, None)
    _broken.discard(name)


def load_enabled():
    for name in config.get("enabled_mods"):
        load(name)
    return LOADED


def reload_all():
    for name in list(LOADED):
        _unload(name)
    return load_enabled()


def enable(name):
    cur = list(config.get("enabled_mods"))
    if name not in cur:
        cur.append(name)
        config.set("enabled_mods", cur)
    return load(name)


def disable(name):
    cur = [m for m in config.get("enabled_mods") if m != name]
    config.set("enabled_mods", cur)
    _unload(name)
    return True, None


# ----------------------------------------------------------------------
# running hooks
# ----------------------------------------------------------------------
def run(name, *args, **kw):
    results = []
    for fn in list(HOOKS.get(name, [])):
        origin = getattr(fn, "_mod", fn.__module__)
        if origin in _broken:
            continue
        try:
            results.append(fn(*args, **kw))
        except Exception as e:
            _broken.add(origin)
            print(f"[mods] {origin}.{name} raised, disabled for this run: {e}")
    return results


def chain(name, value, *args):
    for fn in list(HOOKS.get(name, [])):
        origin = getattr(fn, "_mod", fn.__module__)
        if origin in _broken:
            continue
        try:
            out = fn(value, *args)
            if out is not None:
                value = out
        except Exception as e:
            _broken.add(origin)
            print(f"[mods] {origin}.{name} raised, disabled for this run: {e}")
    return value


def try_voice_command(text, ctx):
    """First mod command whose pattern matches wins. Returns reply or None."""
    for rx, fn, origin in COMMANDS:
        if origin in _broken:
            continue
        m = rx.search(text)
        if not m:
            continue
        try:
            out = fn(m, ctx)
        except Exception as e:
            _broken.add(origin)
            print(f"[mods] {origin} voice command raised: {e}")
            continue
        if out is not None:
            return str(out)
    return None


def install_example():
    """Copy the bundled example mod into the user's mods folder if empty."""
    src = Path(__file__).resolve().parent.parent / "mods" / "example" / "mod.py"
    dst = config.MODS_DIR / "example" / "mod.py"
    if src.exists() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())
