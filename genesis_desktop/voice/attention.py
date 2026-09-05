"""Is the user talking to me?

The hard part of an always-listening assistant is not hearing words, it is
knowing which ones were meant for it. Rules, in order:

  push    the button/key was held: everything heard is for me
  off     nothing is for me
  wake    for me if it starts with (or leads with) a wake word, or if we are
          inside the follow-up window after my last reply
  always  same as wake, unless require_name_in_always is off, in which case
          everything is for me

A bare wake word ("Alfred?") is an attention call: answer with a short
prompt and open a listening window rather than sending "alfred" to the
model. Wake words are the persona names plus "genesis" unless configured.
"""
from __future__ import annotations

import re
import time

from .. import config

ATTENTION_ONLY = {"", "hey", "hi", "hello", "yes", "yo", "excuse me", "are you there",
                  "you there", "hey there", "listen", "ok", "okay"}
LEADERS = ("hey", "hi", "ok", "okay", "yo", "excuse me", "listen", "oi", "computer")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", s.lower())).strip()


def title_aliases(title: str) -> list[str]:
    t = _norm(title or "")
    if not t:
        return []
    out = [t]
    words = t.split()
    honorifics = {"dr": "doctor", "mr": "mister", "mrs": "missus", "ms": "miss", "prof": "professor"}
    if words and words[0] in honorifics:
        out.append(" ".join([honorifics[words[0]]] + words[1:]))
        out.append(" ".join(words[1:]))
    elif words and words[0] in honorifics.values():
        out.append(" ".join(words[1:]))
    return [a for a in out if a]


class Attention:
    def __init__(self, persona_names=(), titles=()):
        self.persona_names = []
        self.set_personas(persona_names, titles)
        self._follow_until = 0.0
        self._armed_until = 0.0
        self.pushed = False        # push-to-talk currently held

    # ------------------------------------------------------------------
    @property
    def mode(self):
        return config.get("voice_mode")

    def wake_words(self) -> list[str]:
        ws = [w.lower().strip() for w in config.get("wake_words") if w.strip()]
        if not ws:
            ws = list(self.persona_names) + ["genesis"]
        return sorted(set(ws), key=len, reverse=True)

    def set_personas(self, names, titles=()):
        """Names plus spoken forms of titles: "Dr. House" gives "dr house",
        "doctor house" and "house"."""
        out = []
        for n in names:
            out.append(_norm(n))
        for t in titles:
            for alias in title_aliases(t):
                if alias not in out:
                    out.append(alias)
        self.persona_names = [a for a in out if a]

    # ------------------------------------------------------------------
    def note_reply_finished(self):
        self._follow_until = time.monotonic() + float(config.get("follow_up_seconds"))

    def arm(self, seconds=8.0):
        """Open a window where no wake word is needed (after "Alfred?")."""
        self._armed_until = time.monotonic() + seconds

    def disarm(self):
        self._armed_until = 0.0
        self._follow_until = 0.0

    def window_open(self) -> bool:
        now = time.monotonic()
        return now < self._follow_until or now < self._armed_until

    # ------------------------------------------------------------------
    def find_wake(self, text: str):
        """(wake_word, remainder) if the text leads with a wake word."""
        t = _norm(text)
        if not t:
            return None, t
        for w in self.wake_words():
            pat = rf"^(?:(?:{'|'.join(map(re.escape, LEADERS))})[ ,]+)?{re.escape(w)}\b[ ,.?!]*(.*)$"
            m = re.match(pat, t)
            if m:
                return w, m.group(1).strip()
        # the name a couple of words in: "can you alfred check the disk"
        words = t.split()
        for i, word in enumerate(words[:3]):
            if word in self.wake_words():
                rest = " ".join(words[:i] + words[i + 1:]).strip()
                return word, rest
        return None, t

    def heard_wake(self, partial: str) -> bool:
        """Quick check on a streaming partial: has the name been said?"""
        t = _norm(partial)
        return any(re.search(rf"\b{re.escape(w)}\b", t) for w in self.wake_words())

    def check(self, text: str):
        """-> (addressed: bool, text_for_model: str, attention_only: bool)"""
        mode = self.mode
        if mode == "off":
            return False, text, False
        if mode == "push" or self.pushed:
            wake, rest = self.find_wake(text)
            return True, (rest if wake else text.strip()), (wake is not None and _norm(rest) in ATTENTION_ONLY)
        wake, rest = self.find_wake(text)
        if wake is not None:
            return True, rest, _norm(rest) in ATTENTION_ONLY
        if self.window_open():
            return True, text.strip(), False
        if mode == "always" and not config.get("require_name_in_always"):
            return True, text.strip(), False
        return False, text, False
