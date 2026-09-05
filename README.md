# Genesis Desktop

A native desktop voice client for the [Genesis](https://github.com/rpamperin/Genesis)
assistant backend. Talk to Alfred, Yui, Dr. House or any persona you add on
the backend, watch the assistant react, and let Alfred look at and fix the
computer you are sitting at.

Built with Qt (PySide6). No browser, no Electron. Installed separately from
the backend; it only needs the backend's URL.

```
  ┌────────────────────────────────────────────────────────────────┐
  │ Agent [Alfred ▾]  Mode [Wake word ▾]   ● Hold to talk  Mute … │
  │                                                                │
  │ Activity ▏           A L F R E D             ▕ Chat (optional) │
  │ heard    ▏          L I S T E N I N G        ▕                 │
  │ tool     ▏               ◉ ◉ ◉               ▕  you: …         │
  │ reply    ▏        ( voice-reactive orb )     ▕  alfred: …      │
  │          ▏                                   ▕                 │
  │          ▏        "how full is the disk"     ▕                 │
  ├────────────────────────────────────────────────────────────────┤
  │ ⚙ ollama · qwen2.5  ◉ Alfred  ◎ wake word  🎙 mic on  👂 vosk  │
  └────────────────────────────────────────────────────────────────┘
```

## What it does

- **Voice first.** Say the name, then ask. The reply is read out, sentence by
  sentence, while the model is still writing. The chat panel is there if you
  want it and hidden if you do not.
- **Knows when you are talking to it.** Wake word ("Alfred, …", "hey Yui …"),
  a follow-up window after each reply so you do not repeat the name, push to
  talk (hold the button or Space), or always-on. A bare "Alfred?" gets a
  "Yes?" and an open ear. Say the name while it is talking to interrupt.
- **A face that moves.** The default view is an actual character: it looks
  at you while it listens, its eyes widen and it leans in when it hears you,
  it glances up and away with one brow raised while it thinks, and its mouth
  moves with the sound of its own voice — driven by the same audio the
  speaker is playing, so the lips cannot drift out of sync. Each persona
  gets its own face, built from a handful of numbers (skin, hair, brow
  weight, eye size, stubble, jaw, lip fullness) and tinted by the accent
  colour the backend gives it; there is no model file to download. Alfred is
  a bald butler in a bow tie, Yui is bright-eyed, House is unshaven with
  heavy brows. Abstract orb, bars and ring styles are still there in
  Settings.
- **The mouth is not one ellipse.** Upper and lower lips are separate shapes
  with a cupid's bow; the jaw drops and lengthens the chin; the corners pull
  wide or purse round; teeth appear behind the top lip and the tongue shows
  on the wide vowels. Loudness sets how far it opens and a separate channel
  sets *how*, changing at syllable rate, so speech alternates between wide,
  round and narrow instead of chewing.
- **Alfred can fix things.** Tools run on this machine: a real shell, files
  anywhere you can reach, services, logs, packages, processes, notifications,
  opening things, clipboard, screenshots, volume. Root actions go through
  `pkexec`, so the desktop asks for your password, never this app.
- **You stay in charge.** Every call is classified. Read-only things just
  run. Anything that changes the machine is shown to you with Allow /
  Always allow / Deny, and you can answer by voice: "yes", "no", "always".
  Three policies: safe (refuse changes), ask (default), trusted.
- **Local mods.** Drop a folder in `~/.config/genesis-desktop/mods/` to add
  tools, spoken commands and hooks that run in this app, independent of the
  backend's mods. Enable them in Settings.
- **Personas come from the backend, voice included.** Whatever
  `GET /personas` returns is what you get: name, title, avatar, accent
  colour, greeting, and voice (name, gender, pitch, speed). The backend
  picks the voice — a persona's voice is part of who it is — and if that
  voice is not on this machine yet the app downloads it in the background
  and speaks with a same-gender stand-in until it lands. "Switch to Doctor House" works by title as well
  as by name, and "House, …" is a wake word. The Agent page can create,
  edit and delete personas on the backend through its admin API.
- **Accounts and conversations.** Log in to a backend with per-person
  accounts (Settings › Connection) so your history and memory are your
  own. The chat panel shows the backend's transcript and lets you pick,
  start or delete conversations. Backend RAM/GPU and token counts show in
  the status strip while it works.
- **A separate settings window** with pages for Connection, Agent, Voice,
  Local tools, Local mods, Backend (the backend's own settings and mods,
  through its admin API), Appearance and Diagnostics.
- **Everything offline if you want it.** Vosk for listening, Piper for
  speaking, both downloadable from Settings > Voice. Falls back to
  espeak-ng or the backend's voice endpoints. Whisper is optional for
  better transcripts.
- Also: system tray with mute and quick show, optional backend autostart,
  transcript logs, light and dark themes, keyboard shortcuts
  (Space push-to-talk, Esc stop, Ctrl+M mute, Ctrl+T chat, Ctrl+L activity,
  Ctrl+, settings).

## Install (Ubuntu)

```bash
git clone https://github.com/rpamperin/Genesis-desktop
cd Genesis-desktop
./install.sh
```

That installs the system libraries (PortAudio, espeak-ng, policykit), makes
a virtualenv, downloads the small Vosk model and two Piper voices, and adds
"Genesis" to your app menu. Run `./install.sh --no-sudo --no-models` to do
those parts yourself.

Manual:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # core: PySide6, httpx, numpy, sounddevice
pip install vosk piper-tts  # offline listening and speaking
genesis-desktop
```

Then Settings > Connection: backend URL (default `http://127.0.0.1:8080`)
and the tokens if the backend has them set. `genesis-desktop --doctor`
prints what is installed and what is missing.

The backend needs to be at least the version that includes client tools
(`docs/CLIENT_TOOLS.md` in the Genesis repo). Older backends still chat and
speak; Alfred just cannot touch this machine, and the status strip says so.
Backends with the newer persona/accounts API (House, avatars, logins,
sessions, agent stats) are used in full; older ones simply lack those
parts.

## Talking to it

| Say | Does |
|---|---|
| "Alfred, why is the disk full" | a normal turn; Alfred may run `df`, read logs, and so on |
| "Alfred" | "Yes?" and it listens without needing the name again |
| "stop" / "never mind" | interrupt the reply |
| "switch to Yui", "switch to Doctor House" | change persona (each keeps its own history) |
| "yes" / "no" / "always" | answer a tool approval |
| "mute" / "wake up" | microphone off / on |
| "show the chat", "open settings", "show the activity" | UI |
| "repeat that", "speak slower", "louder" | speech |
| "what can you do" | the short version of this table |

Anything else goes to the model. Type in the chat panel if you would rather
not talk.

## Local tools and the policy

| Tool | Read-only | Changes |
|---|---|---|
| `run_command` | `df`, `ls`, `journalctl`, `systemctl status`, pipes of those… | anything else, redirects, `sudo`, unknown programs |
| `read_file`, `list_directory`, `search_files`, `system_info`, `processes`, `system_logs`, `screenshot`, `current_time` | always | |
| `write_file`, `open`, `clipboard set`, `volume set` | | asks |
| `service` | status, logs | start/stop/restart/enable (root) |
| `packages` | search, info, installed | install/remove/upgrade (root) |

"Always allow this" remembers the exact command line, nothing looser. The
list is in Settings > Local tools. Relative paths resolve against the work
directory (your home folder unless changed).

## Writing a local mod

`~/.config/genesis-desktop/mods/<name>/mod.py`:

```python
from genesis_desktop import mods

@mods.voice_command(r"\b(what|which) day is it\b")
def today(match, ctx):
    import datetime
    return datetime.date.today().strftime("It's %A.")

@mods.tool({"type": "function", "function": {
    "name": "battery", "description": "Battery state",
    "parameters": {"type": "object", "properties": {}}}}, risk="safe")
def battery():
    ...

@mods.hook("before_send")       # also: startup, after_reply, on_state, shutdown
def edit(ctx):
    return ctx                  # or set ctx["handled"] = "reply" to answer locally
```

The bundled example mod (copied into the mods folder on first run) shows
everything. A mod that raises while loading is marked broken and skipped;
a hook that raises is dropped for the rest of the run.

## Layout

```
genesis_desktop/
├── config.py         local settings, layered like the backend's
├── client.py         Genesis HTTP client, SSE turns, client-tool round trip
├── controller.py     the state machine; every thread reports through Qt signals
├── commands.py       built-in spoken commands
├── mods.py           local mod loader
├── doctor.py         what is missing
├── tools/            registry, policy, system and desktop tools
├── voice/            audio capture/playback, stt (vosk/whisper/backend),
│                     tts (piper/backend/espeak/qt), attention rules
└── ui/               visualizer, panels, status strip, settings window
```

## Tests

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen pytest -q
```

Runs headless in a few seconds against a stdlib fake of the Genesis API
(`tests/fake_backend.py`). No microphone, no model, no network. Covers the
settings layering, the tool policy, the attention rules, SSE parsing, the
client-tool round trip, local mods, spoken commands, sentence streaming and
the controller's states. `tests/smoke_ui.py` drives the real window and
writes screenshots.

## Notes

- The backend does the thinking. This app never talks to a model directly.
- The microphone is paused while it speaks unless barge-in is on; with
  barge-in, only the wake word interrupts, so it does not hear itself.
- Voice per persona: whatever the backend says, fetched on demand. Only an
  explicit override in Settings beats it. Pitch and speed apply on espeak-ng
  and Qt speech; Piper has no pitch knob.
- Settings live in `~/.config/genesis-desktop/settings.json`; models and
  logs in `~/.local/share/genesis-desktop/`. Environment variables
  `GENESIS_DESKTOP_<KEY>` override any setting.
