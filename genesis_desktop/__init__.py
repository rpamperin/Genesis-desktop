"""Genesis Desktop -- a native voice client for the Genesis backend.

The backend (Genesis) does the thinking. This program owns the microphone,
the speaker, the screen and the machine it is installed on. It is installed
separately and talks to Genesis over HTTP, so the two can live on different
computers.

Layout:

    config.py        local settings (~/.config/genesis-desktop/settings.json)
    client.py        HTTP client for the Genesis API, SSE streaming
    controller.py    the state machine: listening -> thinking -> speaking
    voice/           microphone, wake word, speech to text, text to speech
    tools/           tools that run on THIS machine, with a permission policy
    mods.py          local drop-in extensions, independent of backend mods
    ui/              Qt widgets: visualizer, status, chat, settings window
"""
__version__ = "0.1.0"
APP_NAME = "Genesis"
