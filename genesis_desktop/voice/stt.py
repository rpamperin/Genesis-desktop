"""Speech to text.

Three engines. Vosk is the workhorse: offline, small, streams partial
results as you talk, which is what makes wake-word spotting and the "it
heard me" animation feel immediate. Whisper (faster-whisper) is more
accurate but batch-only, so when it is selected Vosk still does the
listening and whisper re-transcribes the finished utterance. The backend
engine posts the finished clip to Genesis's /transcribe.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np

from .. import config

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"


def vosk_ready() -> tuple[bool, str]:
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False, "vosk is not installed (pip install vosk)"
    d = config.vosk_model_dir()
    if not (d / "conf").exists() and not (d / "am").exists():
        return False, f"no vosk model at {d} (Settings > Voice > Download)"
    return True, str(d)


def whisper_ready() -> tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False, "faster-whisper is not installed (pip install faster-whisper)"
    return True, config.get("whisper_model")


def download_vosk_model(progress=None) -> Path:
    """Fetch the small English model into the models dir. Blocking."""
    dest = config.vosk_model_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    zpath = dest.parent / "vosk-model.zip"
    with urllib.request.urlopen(VOSK_MODEL_URL, timeout=60) as r, open(zpath, "wb") as f:
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
    tmp = dest.parent / "vosk-unpack"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    inner = next(p for p in tmp.iterdir() if p.is_dir())
    shutil.rmtree(dest, ignore_errors=True)
    inner.rename(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    zpath.unlink(missing_ok=True)
    return dest


# ----------------------------------------------------------------------
class VoskRecognizer:
    """Streaming. feed() returns the running partial; finish() the final."""
    streaming = True

    _model = None
    _model_dir = None

    def __init__(self, sample_rate=16000):
        import vosk
        vosk.SetLogLevel(-1)
        d = str(config.vosk_model_dir())
        if VoskRecognizer._model is None or VoskRecognizer._model_dir != d:
            VoskRecognizer._model = vosk.Model(d)
            VoskRecognizer._model_dir = d
        self._rec = vosk.KaldiRecognizer(VoskRecognizer._model, sample_rate)
        self._rec.SetWords(False)
        self.partial = ""
        self._final_parts = []

    def feed(self, pcm16: bytes) -> str:
        if self._rec.AcceptWaveform(pcm16):
            res = json.loads(self._rec.Result() or "{}").get("text", "")
            if res:
                self._final_parts.append(res)
            self.partial = ""
        else:
            self.partial = json.loads(self._rec.PartialResult() or "{}").get("partial", "")
        return " ".join(self._final_parts + ([self.partial] if self.partial else [])).strip()

    def finish(self) -> str:
        res = json.loads(self._rec.FinalResult() or "{}").get("text", "")
        if res:
            self._final_parts.append(res)
        text = " ".join(self._final_parts).strip()
        self.reset()
        return text

    def reset(self):
        self._rec.Reset()
        self.partial = ""
        self._final_parts = []


class WhisperTranscriber:
    streaming = False
    _model = None
    _name = None

    def __init__(self):
        from faster_whisper import WhisperModel
        name = config.get("whisper_model")
        if WhisperTranscriber._model is None or WhisperTranscriber._name != name:
            WhisperTranscriber._model = WhisperModel(name, device="auto", compute_type="int8")
            WhisperTranscriber._name = name

    def transcribe(self, pcm16: bytes, sample_rate=16000) -> str:
        a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000:
            idx = np.linspace(0, len(a) - 1, int(len(a) * 16000 / sample_rate))
            a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
        segments, _ = WhisperTranscriber._model.transcribe(a, vad_filter=True, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()


class BackendTranscriber:
    streaming = False

    def __init__(self, client):
        self.client = client

    def transcribe(self, pcm16: bytes, sample_rate=16000) -> str:
        from .audio import pcm_to_wav
        return self.client.transcribe(pcm_to_wav(pcm16, sample_rate))


def pick_engine(client=None) -> tuple[Optional[str], str]:
    """Resolve 'auto'. Returns (engine_name or None, reason)."""
    want = config.get("stt_engine")
    v_ok, v_msg = vosk_ready()
    if want == "vosk":
        return ("vosk", v_msg) if v_ok else (None, v_msg)
    if want == "whisper":
        w_ok, w_msg = whisper_ready()
        return ("whisper", w_msg) if w_ok else (None, w_msg)
    if want == "backend":
        return "backend", "backend /transcribe"
    if v_ok:
        return "vosk", v_msg
    w_ok, w_msg = whisper_ready()
    if w_ok:
        return "whisper", w_msg
    return None, v_msg


def make_finisher(engine: str, client=None):
    """A batch transcriber for the finished utterance, or None to keep
    the streaming recognizer's text."""
    if engine == "whisper":
        return WhisperTranscriber()
    if engine == "backend":
        return BackendTranscriber(client)
    return None
