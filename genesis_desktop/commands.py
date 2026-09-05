"""Built-in voice commands, handled before anything reaches the backend.

Short, common things that should not cost a model round trip: stop, switch
persona, mute, show the chat, open settings. Local mods can add more with
@mods.voice_command; those are tried after these.

Each handler returns None (not mine) or a dict:
    {"say": "text to speak"}            reply locally
    {"action": "name", ...}             ask the controller to do something
"""
from __future__ import annotations

import re

_RULES = []


def rule(pattern):
    rx = re.compile(pattern, re.IGNORECASE)

    def deco(fn):
        _RULES.append((rx, fn))
        return fn
    return deco


def match(text: str, personas: list[str]):
    t = text.strip().rstrip(".!?").strip()
    for rx, fn in _RULES:
        m = rx.fullmatch(t) if getattr(fn, "_full", True) else rx.search(t)
        if m:
            out = fn(m, personas)
            if out is not None:
                return out
    return None


@rule(r"(stop|cancel|never ?mind|forget it|shut up|quiet|be quiet|enough|that's enough|hush)( please)?( now)?")
def _stop(m, personas):
    return {"action": "interrupt"}


def _resolve(spoken: str, personas):
    """personas: names, or a {alias: name} mapping (aliases include spoken
    titles such as "doctor house")."""
    s = re.sub(r"[^a-z0-9 ]+", " ", spoken.lower()).strip()
    if isinstance(personas, dict):
        if s in personas:
            return personas[s]
        for alias, name in sorted(personas.items(), key=lambda kv: -len(kv[0])):
            if s.endswith(alias) or s.startswith(alias):
                return name
        return None
    return s if s in personas else None


@rule(r"(switch|change|talk|speak|hand( me)? over|go) (to|with) (?P<name>[a-z. ]+?)( please)?")
def _switch(m, personas):
    name = _resolve(m.group("name"), personas)
    return {"action": "persona", "name": name} if name else None


@rule(r"(?P<name>[a-z. ]+?)[, ]+(are you|you) there")
def _there(m, personas):
    name = _resolve(m.group("name"), personas)
    return {"action": "persona", "name": name, "say": "Yes, I'm here."} if name else None


@rule(r"(mute|stop listening|go to sleep|sleep|mic off|microphone off|stop the mic)( please)?")
def _mute(m, personas):
    return {"action": "mute", "value": True}


@rule(r"(unmute|start listening|wake up|mic on|microphone on)( please)?")
def _unmute(m, personas):
    return {"action": "mute", "value": False}


@rule(r"(show|open|display) (the )?(chat|text|transcript|conversation)( (view|panel|window))?")
def _show_chat(m, personas):
    return {"action": "chat", "value": True}


@rule(r"(hide|close) (the )?(chat|text|transcript|conversation)( (view|panel|window))?")
def _hide_chat(m, personas):
    return {"action": "chat", "value": False}


@rule(r"(show|open) (the )?(activity|log|tools?|tool log)( (view|panel|window))?")
def _show_activity(m, personas):
    return {"action": "activity", "value": True}


@rule(r"(open|show) (the )?(settings|preferences|options|config(uration)?)")
def _settings(m, personas):
    return {"action": "settings"}


@rule(r"(repeat|say that again|what did you say|pardon|come again|say again)( please)?")
def _repeat(m, personas):
    return {"action": "repeat"}


@rule(r"(clear|reset|forget) (the |this |our )?(history|conversation|chat|memory)( please)?")
def _clear(m, personas):
    return {"action": "clear_history"}


@rule(r"(what can you do|help|what do you do|what are your commands|list commands)")
def _help(m, personas):
    names = sorted(set(personas.values())) if isinstance(personas, dict) else list(personas)
    names = " or ".join(n.title() for n in names) or "me"
    return {"say": (
        f"Say my name, then ask. I can look at this computer, read and write "
        f"files, check services and logs, install packages, open things, and "
        f"take screenshots. Changes are shown to you first. Say stop to "
        f"interrupt, switch to {names} to change assistant, mute to stop "
        f"listening, and show chat to see the text.")}


@rule(r"(speak|talk) (slower|faster)")
def _rate(m, personas):
    return {"action": "rate", "delta": -0.15 if "slower" in m.group(0).lower() else 0.15}


@rule(r"(be )?(quieter|louder)")
def _vol(m, personas):
    return {"action": "volume", "delta": -10 if "quiet" in m.group(0).lower() else 10}


@rule(r"(thanks|thank you|cheers|good job|well done|nice one)( [a-z]+)?")
def _thanks(m, personas):
    return {"say": "You're welcome."}


@rule(r"(yes|yeah|yep|allow|go ahead|do it|approve|ok|okay|confirm|sure)( please)?")
def _yes(m, personas):
    return {"action": "confirm", "value": True}


@rule(r"(no|nope|deny|don't|do not|cancel that|refuse|reject|stop that)( please)?")
def _no(m, personas):
    return {"action": "confirm", "value": False}


@rule(r"(always allow|always|allow always|remember (that|this))( please)?")
def _always(m, personas):
    return {"action": "confirm", "value": True, "always": True}


_YES = re.compile(r"^\W*(yes|yeah|yep|yup|allow|go ahead|do it|approve|ok|okay|confirm|sure|fine|please do|alright|all right)\b", re.I)
_NO = re.compile(r"^\W*(no|nope|nah|deny|don't|do not|cancel|refuse|reject|stop|negative)\b", re.I)
_ALWAYS = re.compile(r"\b(always|remember (that|this)|every time|from now on)\b", re.I)


def confirm_answer(text: str):
    """While a tool approval is pending, be lenient: a leading yes/no word
    decides, "always" upgrades a yes. None if it is not an answer."""
    t = text.strip()
    if _ALWAYS.search(t) and not _NO.match(t):
        return {"value": True, "always": True}
    if _YES.match(t):
        return {"value": True}
    if _NO.match(t):
        return {"value": False}
    return None
