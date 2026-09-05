"""Microphone capture and audio playback.

Capture runs its own thread and hands 100 ms chunks of 16 kHz mono int16 to
a callback along with an RMS level. Playback takes WAV bytes and reports a
level while it plays, so the visualizer can move with the voice.

sounddevice (PortAudio) is the normal path. If it is missing, capture is
unavailable and playback falls back to paplay/aplay with a synthetic level
envelope computed from the samples, so the picture still moves.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
    SD_ERROR = None
except Exception as e:      # ImportError or OSError (no libportaudio)
    sd = None
    SD_ERROR = str(e)


def available() -> bool:
    return sd is not None


def input_devices():
    """[(index, name)] for devices with input channels."""
    if not sd:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d["name"]))
    except Exception:
        pass
    return out


def output_devices():
    if not sd:
        return []
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_output_channels", 0) > 0:
                out.append((i, d["name"]))
    except Exception:
        pass
    return out


def _device_index(name_or_idx, kind):
    if name_or_idx in ("", None):
        return None
    try:
        return int(name_or_idx)
    except (TypeError, ValueError):
        pass
    devs = input_devices() if kind == "input" else output_devices()
    for i, n in devs:
        if name_or_idx.lower() in n.lower():
            return i
    return None


def rms(pcm16: bytes) -> float:
    if not pcm16:
        return 0.0
    a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if a.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(a * a)))


# ----------------------------------------------------------------------
# capture
# ----------------------------------------------------------------------
class Capture:
    """Microphone -> on_chunk(pcm16_bytes, level). Thread-safe start/stop."""

    def __init__(self, sample_rate=16000, chunk_ms=100, device=""):
        self.sample_rate = sample_rate
        self.chunk = int(sample_rate * chunk_ms / 1000)
        self.device = device
        self.on_chunk: Optional[Callable[[bytes, float], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.paused = False          # drop audio (while we are speaking)
        self._stream = None
        self._lock = threading.Lock()
        self.error = SD_ERROR
        self.running = False

    def start(self) -> bool:
        if not sd:
            self.error = f"sounddevice unavailable: {SD_ERROR}"
            return False
        with self._lock:
            if self._stream:
                return True
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate, channels=1, dtype="int16",
                    blocksize=self.chunk, device=_device_index(self.device, "input"),
                    callback=self._cb,
                )
                self._stream.start()
                self.running = True
                self.error = None
                return True
            except Exception as e:
                self.error = f"microphone: {e}"
                self._stream = None
                return False

    def stop(self):
        with self._lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self.running = False

    def _cb(self, indata, frames, t, status):
        if status and self.on_error:
            try:
                self.on_error(str(status))
            except Exception:
                pass
        if self.paused or not self.on_chunk:
            return
        data = bytes(indata.tobytes())
        try:
            self.on_chunk(data, rms(data))
        except Exception as e:
            if self.on_error:
                self.on_error(f"capture handler: {e}")


# ----------------------------------------------------------------------
# wav helpers
# ----------------------------------------------------------------------
def pcm_to_wav(pcm16: bytes, sample_rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def wav_to_pcm(wav: bytes):
    """-> (pcm16 bytes, sample_rate, channels)"""
    with wave.open(io.BytesIO(wav), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if sw != 2:
        a = np.frombuffer(frames, dtype=np.uint8 if sw == 1 else np.int32)
        a = (a.astype(np.float32) - 128) * 256 if sw == 1 else a.astype(np.float32) / 65536
        frames = a.astype(np.int16).tobytes()
    return frames, sr, ch


def envelope(pcm16: bytes, sample_rate: int, channels: int, step_ms=50):
    """[(t_seconds, level)] -- for a fake level meter during subprocess playback."""
    a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    n = max(1, int(sample_rate * step_ms / 1000))
    out = []
    for i in range(0, len(a), n):
        seg = a[i:i + n]
        out.append((i / sample_rate, float(np.sqrt(np.mean(seg * seg))) if seg.size else 0.0))
    return out


# ----------------------------------------------------------------------
# playback
# ----------------------------------------------------------------------
class Player:
    """Play WAV bytes, blocking, reporting a level. stop() cuts it short."""

    def __init__(self, device=""):
        self.device = device
        self.on_level: Optional[Callable[[float], None]] = None
        self._stop = threading.Event()
        self._proc = None
        self.error = None

    def stop(self):
        self._stop.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def play(self, wav: bytes) -> bool:
        self._stop.clear()
        try:
            pcm, sr, ch = wav_to_pcm(wav)
        except Exception as e:
            self.error = f"bad wav: {e}"
            return False
        if sd:
            return self._play_sd(pcm, sr, ch)
        return self._play_subprocess(wav, pcm, sr, ch)

    def _play_sd(self, pcm, sr, ch) -> bool:
        a = np.frombuffer(pcm, dtype=np.int16).reshape(-1, ch)
        block = int(sr * 0.05)
        pos = 0
        try:
            with sd.OutputStream(samplerate=sr, channels=ch, dtype="int16",
                                 device=_device_index(self.device, "output")) as out:
                while pos < len(a) and not self._stop.is_set():
                    seg = a[pos:pos + block]
                    pos += block
                    if self.on_level:
                        f = seg.astype(np.float32) / 32768.0
                        self.on_level(float(np.sqrt(np.mean(f * f))) if f.size else 0.0)
                    out.write(np.ascontiguousarray(seg))
        except Exception as e:
            self.error = f"playback: {e}"
            return self._play_subprocess(pcm_to_wav(pcm, sr) if ch == 1 else None, pcm, sr, ch)
        finally:
            if self.on_level:
                self.on_level(0.0)
        return True

    def _play_subprocess(self, wav, pcm, sr, ch) -> bool:
        exe = shutil.which("paplay") or shutil.which("aplay") or shutil.which("ffplay")
        if not exe or wav is None:
            self.error = "no audio output: install PortAudio (libportaudio2) or pulseaudio-utils"
            return False
        argv = [exe, "-"] if "paplay" in exe else ([exe, "-q", "-"] if "aplay" in exe else
                                                     [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", "-"])
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.error = f"playback: {e}"
            return False
        threading.Thread(target=self._feed, args=(self._proc, wav), daemon=True).start()
        start = time.monotonic()
        for t, lvl in envelope(pcm, sr, ch):
            if self._stop.is_set() or self._proc.poll() is not None:
                break
            delay = start + t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if self.on_level:
                self.on_level(lvl)
        try:
            self._proc.wait(timeout=5)
        except Exception:
            pass
        if self.on_level:
            self.on_level(0.0)
        self._proc = None
        return True

    @staticmethod
    def _feed(proc, data):
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except Exception:
            pass
