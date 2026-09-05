# Genesis Desktop — User Guide

A voice assistant that lives on your Ubuntu desktop. You say its name, ask
for something, and it answers out loud. It can also look at your computer and
fix things when you ask it to.

---

## What you need

Two pieces, installed separately:

1. **The Genesis backend** — the part that thinks. It runs the model, keeps
   your history, and holds your documents. It can run on this machine or on
   another one on your network.
2. **Genesis Desktop** — this app. It owns the microphone, the speaker, the
   screen and this computer. It talks to the backend over the network.

You also want a microphone and speakers, and about 200 MB of disk for the
offline voice files.

---

## Installing

In a terminal:

```
git clone https://github.com/rpamperin/Genesis-desktop
cd Genesis-desktop
./install.sh
```

The installer asks for your password once, to install the system audio
libraries. It then makes its own Python environment, downloads the offline
listening model and two voices, and adds **Genesis** to your applications
menu.

If you would rather install the system parts yourself, run
`./install.sh --no-sudo --no-models`.

---

## Starting it

**First, start the backend.** In its own terminal:

```
cd ~/Genesis
source .venv/bin/activate
python -m genesis serve
```

Leave that window open. It listens on `http://127.0.0.1:8080`.

**Then start the app.** Either open **Genesis** from your applications menu,
or type `genesis-desktop` in a terminal.

**To skip the first step**, open Settings → Connection and turn on *Start the
backend when this app starts*. Point it at your Genesis folder and set the
command to `.venv/bin/python -m genesis serve`. After that you only ever
launch the app.

### First-run checklist

1. **Settings → Connection.** Check the backend address. Add the tokens only
   if your backend has them set. Press *Test connection*.
2. **Settings → Voice.** Talk and watch the *Level* bar move. If it does not,
   pick a different input device.
3. Say **"Alfred"**, wait for *"Yes?"*, then ask your question.

---

## Reading the window

In the middle is the assistant's face. Each one looks different — Alfred is
a greying butler in a bow tie, Yui is bright-eyed, House is unshaven with
heavy brows — and it tells you what is happening without your having to read
anything.

| What it does | What it means |
|---|---|
| Looks around slowly, blinks | Listening for its name |
| Eyes widen, leans in, green rings | It hears you — keep talking |
| Glances up and away, one brow raised | Thinking about your answer |
| Looks aside, amber dots | Running something on your computer |
| Eyes wide, brows up | Waiting for you to say yes or no |
| Mouth moving with the sound | Speaking |
| Eyes closed, head down, grey | Muted, or the backend is not reachable |

Its mouth is driven by the actual sound of its voice, so it moves in time
with the words rather than flapping on a timer. The lips spread, purse and
round as it talks, and you will see teeth and a tongue on the wide vowels.

If you would rather have a shape than a face, Settings → Appearance also has
an orb, a bar meter and a ring.

Underneath the shape you see what it heard you say, and then what it is
saying back.

The strip along the bottom shows the model in use, which assistant is
active, the listening mode, your microphone, and the speech engines. If
something is missing, that is where it says so.

Two side panels are optional:

- **Chat** (Ctrl+T) — the conversation in text, and a box to type instead of
  talking. Also lets you switch between saved conversations.
- **Activity** (Ctrl+L) — everything it heard, ran, was allowed and was
  refused. Click a line to see the full output.

---

## Talking to it

Say its name first, then what you want:

> "Alfred, why is my disk full?"

After it answers, you have about eight seconds to keep going without saying
the name again. So you can just add "and what's using the most space?"

Say the name on its own — **"Alfred?"** — and it answers *"Yes?"* and listens.

**To interrupt**, say its name while it is talking, or press Escape.

### Four ways to listen

Set this in the toolbar or Settings → Voice.

- **Wake word** — the normal way. It only answers when you say the name.
- **Push to talk** — nothing is heard unless you hold the button or the
  spacebar. The most private option.
- **Always on** — no name needed. Handy when your hands are busy.
- **Voice off** — type only.

---

## The assistants

Which ones you get depends on your backend. Switch with the toolbar picker or
by saying "switch to Yui".

- **Alfred** 🎩 — a butler, terse and technical. This is the one that looks at
  your computer and fixes things.
- **Yui** 🌟 — warm and chatty. Office admin, letters, scheduling, organising,
  thinking out loud. Good for everyday paperwork.
- **Dr. House** 🩺 — blunt and sarcastic, works through medical questions like
  a diagnosis. Treat him as a well-read character, not a doctor: he has not
  examined anyone and cannot see any test results. For anything urgent or
  worrying, see a real doctor.

You can talk to House by title too — "switch to Doctor House" works, and so
does "House, ...".

Each assistant keeps its own separate memory. Talking to one never leaks into
another.

---

## Words it understands

These are handled instantly, without asking the model.

| Say | It does |
|---|---|
| "stop", "never mind", "that's enough" | Stops talking right now |
| "switch to Yui", "talk to Doctor House" | Changes assistant |
| "yes" / "no" / "always" | Answers a permission request |
| "mute", "go to sleep" | Stops listening |
| "wake up", "start listening" | Listens again |
| "show the chat" / "hide the chat" | The text panel |
| "show the activity" | The log panel |
| "open settings" | The settings window |
| "repeat that", "say that again" | Says the last answer again |
| "speak slower" / "speak faster" | Changes the reading speed |
| "quieter" / "louder" | Changes the volume |
| "clear the history" | Wipes this conversation |
| "what can you do" | A short spoken summary |

Anything else goes to the assistant.

---

## Letting it work on your computer

This is the part that makes it more than a chat window. When you ask Alfred
something about this machine, he can actually go and look.

He can read files and folders, search them, check disk space, memory and
running programs, read system logs, check services, look up and install
software, take a screenshot, open files and websites, use the clipboard,
change the volume, and run commands.

### You stay in charge

Every single action is sorted into one of three kinds:

- **Just looking** — reading a file, checking the disk, viewing a log. These
  run straight away.
- **Changing something** — writing a file, restarting a service, installing
  software. These stop and ask you first.
- **Needs root** — your desktop's own password box appears. This app never
  sees or stores your password.

When it asks, a bar appears under the assistant showing exactly the command
it wants to run. You can click **Allow**, **Always allow this** or **Deny**,
or just say "yes", "no" or "always".

"Always allow this" remembers that exact command and nothing broader. You can
review and clear the list in Settings → Local tools.

### Three levels of trust

In Settings → Local tools:

- **Safe** — it may look but never change anything.
- **Ask** — the normal setting. Looking is free, changing needs your yes.
- **Trusted** — it does what it likes. Root still asks for your password.

If you are ever unsure, put it on Safe. Nothing breaks; it just declines to
change things.

---

## The settings window

Open with the Settings button or Ctrl+comma. Eight pages:

- **Connection** — the backend address, tokens, and your login if your
  backend has personal accounts. Also the option to start the backend for you.
- **Agent** — which assistant answers, the wake words, and the voice for each
  one. You can also create, edit and delete assistants here.
- **Voice** — how it listens and how it talks. Listening mode, microphone and
  level meter, how long a pause ends your sentence, and the buttons to
  download the offline listening model and voices. There is a *Test* button
  to hear a voice. Each assistant's voice is chosen on the backend; you only
  set one here if you want to overrule it.
- **Local tools** — the trust level, the always-allowed list, and the folder
  that plain file names are read from.
- **Local mods** — add-ons that run inside this app.
- **Backend** — the backend's own settings and add-ons, if you have its admin
  token. This is where the model and provider are changed.
- **Appearance** — dark or light, the shape of the visualiser, which panels
  open at startup, and whether it starts hidden in the tray.
- **Diagnostics** — a checklist of what is installed and what is missing.
  Start here when something is not working.

---

## Keyboard shortcuts

| Key | Does |
|---|---|
| Hold **Space** | Push to talk |
| **Escape** | Stop talking / cancel |
| **Ctrl+M** | Mute the microphone |
| **Ctrl+T** | Show or hide the chat panel |
| **Ctrl+L** | Show or hide the activity panel |
| **Ctrl+,** | Settings |

---

## When something is wrong

**Run the checklist first.** Settings → Diagnostics, or type
`genesis-desktop --doctor` in a terminal. It lists everything that is
installed and everything that is missing, with the command to fix each one.

**"Offline" in the status bar.** The backend is not running or not reachable.
Start it, then check the address in Settings → Connection.

**It cannot hear me.** Settings → Voice — does the *Level* bar move when you
talk? If not, pick a different input device. If the bar moves but nothing
happens, lower the *Speech threshold*.

**It triggers on the television.** Raise the *Speech threshold*, or switch to
push to talk.

**It cuts me off mid-sentence.** Raise *End of sentence after* to 1200 ms or
more.

**It sounds robotic.** No Piper voice is downloaded yet, so it fell back to
the basic system voice. Settings → Voice → pick a voice → *Download voice*.

**It is using the wrong voice.** The backend chooses each assistant's voice.
If that voice is not on this machine yet, the app downloads it in the
background and uses a stand-in of the same gender meanwhile — so it may
change by itself shortly after you connect. To overrule the backend, set a
voice for that assistant in Settings → Agent.

**Alfred says he cannot touch this computer.** Your backend is an older
version without client tool support. The status bar says so. Update the
backend.

**It talks over itself or hears itself.** Turn off *Let me interrupt by
saying the name while it is talking* in Settings → Voice.

---

## Where your things live

| What | Where |
|---|---|
| Your settings | `~/.config/genesis-desktop/settings.json` |
| Your add-ons | `~/.config/genesis-desktop/mods/` |
| Voices and listening models | `~/.local/share/genesis-desktop/models/` |
| Conversation logs | `~/.local/share/genesis-desktop/logs/` |

Your conversations and documents live on the backend, not here.

---

## A note on privacy

Everything can run offline. The listening (Vosk) and the speaking (Piper)
happen on this machine, and if your backend uses a local model, nothing you
say leaves your house at all.

If you set the backend to use a cloud provider, then what you type and say
goes to that provider — but only what you actually send. It does not stream
your microphone anywhere; audio becomes text on this computer first.

In push-to-talk mode nothing is even listened to unless you are holding the
button.
