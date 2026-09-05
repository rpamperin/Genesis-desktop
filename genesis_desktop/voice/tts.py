"""Text to speech.

Engines produce WAV bytes so one Player handles output and the visualizer
gets a level from whichever engine is in use:

    piper     local, natural voices, the intended default. Uses the piper
              python package when installed, else the `piper` binary.
    backend   Genesis's /speak (piper running on the backend box)
    espeak    espeak-ng, robotic but always there on Ubuntu
    qt        QTextToSpeech (speech-dispatcher); speaks directly, no level

Replies are spoken sentence by sentence as they stream in, so the first
words come out while the model is still writing the rest.
"""
from __future__ import annotations

import queue
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .. import config
from .audio import Player

PIPER_VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
PIPER_VOICES = [
    "en_GB-alan-medium", "en_GB-northern_english_male-medium", "en_GB-cori-high",
    "en_GB-jenny_dioco-medium", "en_US-amy-medium", "en_US-lessac-medium",
    "en_US-ryan-high", "en_US-libritts_r-medium", "en_US-joe-medium",
    "en_US-hfc_male-medium", "en_US-hfc_female-medium", "en_US-kusal-medium",
]
PIPER_VOICE_GENDER = {
    "en_GB-alan-medium": "male", "en_GB-northern_english_male-medium": "male",
    "en_GB-cori-high": "female", "en_GB-jenny_dioco-medium": "female",
    "en_US-amy-medium": "female", "en_US-lessac-medium": "female",
    "en_US-ryan-high": "male", "en_US-libritts_r-medium": "male",
    "en_US-joe-medium": "male", "en_US-hfc_male-medium": "male",
    "en_US-hfc_female-medium": "female", "en_US-kusal-medium": "male",
}
DEFAULT_VOICE = {"male": "en_GB-alan-medium", "female": "en_US-amy-medium", "": "en_GB-alan-medium"}


def downloaded_voices() -> list[str]:
    d = config.piper_voice_dir()
    if not d.exists():
        return []
    return sorted(p.name[:-5] for p in d.glob("*.onnx"))


def resolve_voice(persona: dict, override: str = "") -> str:
    """Which piper voice to use for a persona.

    The backend decides. A persona's voice is part of who it is -- set
    alongside its prompt and temperature -- so whatever `GET /personas`
    says is what we speak with, and the desktop does not second-guess it
    from the voice_gender hint. The only things that come before it are an
    explicit per-persona override in Settings, and (when the backend's
    voice is not on this machine yet) a stand-in so it can still talk while
    the real one downloads.
    """
    if override:
        return override
    want = (persona or {}).get("voice") or ""
    have = downloaded_voices()
    if not want:
        return have[0] if have else DEFAULT_VOICE[""]
    if want in have:
        return want
    return substitute_voice(persona, have)


def substitute_voice(persona: dict, have=None) -> str:
    """A stand-in while the backend's chosen voice is not downloaded yet.
    Prefers one of the same gender so it is not jarring."""
    have = downloaded_voices() if have is None else have
    gender = (persona or {}).get("voice_gender") or ""
    if gender:
        for v in have:
            if PIPER_VOICE_GENDER.get(v) == gender:
                return v
    if have:
        return have[0]
    return DEFAULT_VOICE.get(gender, DEFAULT_VOICE[""])


def missing_voice(persona: dict, override: str = "") -> str:
    """The backend's voice name when it is not on this machine, else ""."""
    want = override or (persona or {}).get("voice") or ""
    if want and want not in downloaded_voices():
        return want
    return ""


def piper_voice_paths(name: str):
    d = config.piper_voice_dir()
    return d / f"{name}.onnx", d / f"{name}.onnx.json"


def piper_voice_url(name: str):
    lang, rest = name.split("-", 1)
    speaker, quality = rest.rsplit("-", 1)
    short = lang.split("_")[0]
    base = f"{PIPER_VOICE_BASE}/{short}/{lang}/{speaker}/{quality}/{name}.onnx"
    return base, base + ".json"


def download_piper_voice(name: str, progress=None) -> Path:
    onnx, meta = piper_voice_paths(name)
    onnx.parent.mkdir(parents=True, exist_ok=True)
    u_onnx, u_meta = piper_voice_url(name)
    for url, dest in ((u_meta, meta), (u_onnx, onnx)):
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
        tmp.replace(dest)
    return onnx


def piper_ready(voice: str) -> tuple[bool, str]:
    onnx, _ = piper_voice_paths(voice)
    if not onnx.exists():
        return False, f"voice {voice} not downloaded (Settings > Voice)"
    try:
        import piper  # noqa: F401
        return True, "piper (python)"
    except ImportError:
        pass
    if shutil.which("piper"):
        return True, "piper (binary)"
    return False, "piper is not installed (pip install piper-tts)"


def espeak_ready():
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    return (True, exe) if exe else (False, "espeak-ng is not installed")


def qt_ready():
    try:
        from PySide6.QtTextToSpeech import QTextToSpeech
        engines = QTextToSpeech.availableEngines()
        return (True, ", ".join(engines)) if engines else (False, "no QtTextToSpeech engine")
    except Exception as e:
        return False, f"QtTextToSpeech unavailable: {e}"


def pick_engine(voice: str, backend_tts: str = "browser") -> tuple[Optional[str], str]:
    want = config.get("tts_engine")
    if want == "off":
        return None, "speech off"
    if want != "auto":
        checks = {"piper": lambda: piper_ready(voice), "backend": lambda: (
            backend_tts == "piper", "backend tts_engine is not piper"),
            "espeak": espeak_ready, "qt": qt_ready}
        ok, msg = checks[want]()
        return (want, msg) if ok else (None, msg)
    ok, msg = piper_ready(voice)
    if ok:
        return "piper", msg
    if backend_tts == "piper":
        return "backend", "backend piper"
    ok, msg2 = espeak_ready()
    if ok:
        return "espeak", "espeak-ng (download a piper voice for a nicer one)"
    ok, msg3 = qt_ready()
    if ok:
        return "qt", msg3
    return None, msg


# ----------------------------------------------------------------------
# synthesis
# ----------------------------------------------------------------------
def synth_piper(text: str, voice: str, rate: float = 1.0, pitch: float = 1.0) -> bytes:
    onnx, _ = piper_voice_paths(voice)
    length_scale = 1.0 / max(0.3, rate)
    try:
        from piper import PiperVoice
        import io
        import wave
        pv = _piper_cache.get(str(onnx))
        if pv is None:
            pv = PiperVoice.load(str(onnx))
            _piper_cache[str(onnx)] = pv
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            try:
                pv.synthesize(text, w, length_scale=length_scale)
            except TypeError:
                # newer piper: synthesize_wav(text, wav_file, syn_config)
                from piper import SynthesisConfig
                pv.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=length_scale))
        return buf.getvalue()
    except ImportError:
        pass
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out = f.name
    try:
        subprocess.run(["piper", "--model", str(onnx), "--output_file", out,
                        "--length_scale", f"{length_scale:.2f}"],
                       input=text, text=True, capture_output=True, timeout=120, check=True)
        return Path(out).read_bytes()
    finally:
        Path(out).unlink(missing_ok=True)


_piper_cache: dict = {}


def synth_espeak(text: str, voice: str = "en-gb", rate: float = 1.0, pitch: float = 1.0,
                 gender: str = "") -> bytes:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    lang = "en-gb" if voice.startswith("en_GB") else "en-us"
    if (gender or PIPER_VOICE_GENDER.get(voice, "")) == "female":
        lang += "+f3"
    wpm = int(165 * rate)
    p = int(max(0, min(99, 50 * pitch)))        # espeak pitch 0-99, 50 = normal
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out = f.name
    try:
        subprocess.run([exe, "-v", lang, "-s", str(wpm), "-p", str(p), "-w", out, text],
                       capture_output=True, timeout=60, check=True)
        return Path(out).read_bytes()
    finally:
        Path(out).unlink(missing_ok=True)


# ----------------------------------------------------------------------
# text preparation
# ----------------------------------------------------------------------
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|(?<=[.!?][\"')\]])\s+|\n{2,}")


def clean_for_speech(text: str) -> str:
    """Markdown and code do not read aloud well. Keep the words."""
    t = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    t = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", t)
    t = re.sub(r"^\s*\|.*\|\s*$", "", t, flags=re.M)      # tables
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_END.split(text) if p and p.strip()]
    return parts


class SentenceBuffer:
    """Feed streaming deltas; get back sentences as they complete."""

    def __init__(self, min_chars=12):
        self.buf = ""
        self.min_chars = min_chars
        self.in_code = False

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        if self.buf.count("```") % 2 == 1:
            return []                     # inside a code block; wait
        # a finished code block is not read out; leave a marker in its place
        self.buf = re.sub(r"```.*?```", " (code shown on screen). ", self.buf, flags=re.S)
        out = []
        while True:
            m = _SENT_END.search(self.buf)
            if not m:
                break
            head, self.buf = self.buf[:m.start()], self.buf[m.end():]
            if len(head.strip()) >= self.min_chars or not self.buf:
                out.append(head)
            else:
                self.buf = head + " " + self.buf     # too short; keep together
                break
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf, ""
        return [rest] if rest.strip() else []


# ----------------------------------------------------------------------
# the speaker: a queue of sentences, synthesized ahead, played in order
# ----------------------------------------------------------------------
class Speaker:
    def __init__(self, client=None):
        self.client = client
        self.player = Player(config.get("output_device"))
        self.engine: Optional[str] = None
        self.engine_note = ""
        self.backend_tts = "browser"
        self.on_level: Optional[Callable[[float], None]] = None
        self.on_speaking: Optional[Callable[[bool], None]] = None
        self.on_sentence: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self._q: "queue.Queue[Optional[tuple[str, str]]]" = queue.Queue()
        self._stop = threading.Event()
        self._speaking = False
        self._gen = 0
        self._qt = None
        self.player.on_level = self._level
        self._thread = threading.Thread(target=self._loop, daemon=True, name="tts")
        self._thread.start()

    # ------------------------------------------------------------------
    def configure(self, voice: str, backend_tts: str = "browser"):
        self.backend_tts = backend_tts
        self.engine, self.engine_note = pick_engine(voice, backend_tts)
        self.player.device = config.get("output_device")
        return self.engine, self.engine_note

    @property
    def speaking(self):
        return self._speaking

    def say(self, text: str, voice: str, style: dict = None):
        """style: {"pitch": float, "rate": float, "gender": str} from the persona."""
        if not text.strip():
            return
        for s in split_sentences(clean_for_speech(text)):
            self._q.put((s, voice, self._gen, style or {}))

    def say_sentence(self, sentence: str, voice: str, style: dict = None):
        s = clean_for_speech(sentence)
        if s:
            self._q.put((s, voice, self._gen, style or {}))

    def stop(self):
        """Drop everything queued and cut the current sentence."""
        self._gen += 1
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self.player.stop()
        if self._qt:
            try:
                self._qt.stop()
            except Exception:
                pass

    def _level(self, v):
        if self.on_level:
            self.on_level(v)

    # ------------------------------------------------------------------
    def _loop(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            text, voice, gen, style = item
            if gen != self._gen:
                continue
            wav = None
            try:
                wav = self._synth(text, voice, style)
            except Exception as e:
                if self.on_error:
                    self.on_error(f"tts: {e}")
                continue
            if gen != self._gen:
                continue
            self._set_speaking(True)
            if self.on_sentence:
                self.on_sentence(text)
            try:
                if wav:
                    self.player.play(wav)
                elif self.engine == "qt":
                    self._speak_qt(text, style)
            except Exception as e:
                if self.on_error:
                    self.on_error(f"playback: {e}")
            if self._q.empty():
                self._set_speaking(False)

    def _set_speaking(self, v):
        if v != self._speaking:
            self._speaking = v
            if self.on_speaking:
                self.on_speaking(v)

    def _synth(self, text, voice, style=None) -> Optional[bytes]:
        style = style or {}
        rate = config.get("tts_rate") * float(style.get("rate") or 1.0)
        pitch = float(style.get("pitch") or 1.0)
        if self.engine == "piper":
            return synth_piper(text, voice, rate, pitch)
        if self.engine == "backend":
            return self.client.speak(text, style.get("persona") or voice_persona(voice))
        if self.engine == "espeak":
            return synth_espeak(text, voice, rate, pitch, style.get("gender", ""))
        if self.engine == "qt":
            return None
        raise RuntimeError(self.engine_note or "no tts engine")

    def _speak_qt(self, text, style=None):
        from PySide6.QtTextToSpeech import QTextToSpeech
        style = style or {}
        if self._qt is None:
            self._qt = QTextToSpeech()
        tts = self._qt
        tts.setRate(config.get("tts_rate") * float(style.get("rate") or 1.0) - 1.0)
        tts.setPitch(max(-1.0, min(1.0, float(style.get("pitch") or 1.0) - 1.0)))
        done = threading.Event()
        def _state(st):
            if st in (QTextToSpeech.State.Ready, QTextToSpeech.State.Error):
                done.set()
        tts.stateChanged.connect(_state)
        tts.say(text)
        t0 = 0
        while not done.wait(0.05):
            t0 += 1
            if self.on_level:
                self.on_level(0.25 + 0.15 * ((t0 % 4) / 4))
        tts.stateChanged.disconnect(_state)
        if self.on_level:
            self.on_level(0.0)


_VOICE_PERSONA: dict = {}


def voice_persona(voice: str) -> str:
    return _VOICE_PERSONA.get(voice, "alfred")


def register_persona_voice(persona: str, voice: str):
    _VOICE_PERSONA[voice] = persona
