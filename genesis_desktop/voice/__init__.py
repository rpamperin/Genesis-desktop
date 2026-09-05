"""Microphone, wake word, speech to text, text to speech.

    audio.py       capture thread and playback; RMS levels for the visualizer
    stt.py         engines: vosk (offline, streaming), faster-whisper, backend
    tts.py         engines: piper (local), backend piper, espeak-ng, Qt
    attention.py   is this utterance for me? wake word, follow-up window

Every engine is optional. Missing dependencies degrade to a clear message in
the status bar and the doctor page, never a crash at startup.
"""
