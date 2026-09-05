"""Headless drive of the whole app against the fake backend. Takes
screenshots into the scratch dir. Run: QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py OUTDIR"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
out.mkdir(parents=True, exist_ok=True)
os.environ["GENESIS_DESKTOP_CONFIG_DIR"] = str(out / "cfg")
os.environ["GENESIS_DESKTOP_DATA_DIR"] = str(out / "data")

import fake_backend  # noqa: E402
srv, url = fake_backend.start()
os.environ["GENESIS_DESKTOP_BACKEND_URL"] = url
os.environ["GENESIS_DESKTOP_GREET_ON_START"] = "0"
os.environ["GENESIS_DESKTOP_SHOW_CHAT"] = "1"
os.environ["GENESIS_DESKTOP_TTS_ENGINE"] = "off"

from PySide6.QtCore import QTimer  # noqa: E402
from genesis_desktop.app import Application  # noqa: E402

app = Application(sys.argv[:1])
ctl = app.controller
errors = []
ctl.error.connect(lambda m: errors.append(m))
steps = []


def shot(name):
    app.window.grab().save(str(out / f"{name}.png"))


def pump(ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.qt.processEvents()
        time.sleep(0.01)


def run():
    try:
        app.window.show()
        ctl.start()
        pump(1500)
        assert ctl.health, f"did not connect: {errors}"
        assert ctl.state == "listening", ctl.state
        shot("01-listening")
        # simulate a voice level
        for i in range(30):
            ctl.level.emit(0.05 + 0.1 * (i % 5))
            pump(20)
        # a plain turn
        ctl.submit("hello there", voice=False)
        pump(1500)
        assert "You said: hello there" in ctl.last_reply, ctl.last_reply
        shot("02-reply")
        # local tool, safe -> auto run
        ctl.submit("how full is the disk", voice=False)
        pump(2500)
        assert "The tool said" in ctl.last_reply, (ctl.last_reply, errors)
        assert ctl.state == "listening", ctl.state
        # local tool, mutating -> ask
        ctl.submit("delete the temp thing", voice=False)
        pump(1200)
        assert ctl.state == "confirm", ctl.state
        assert app.window.approval.isVisible()
        shot("03-confirm")
        ctl.resolve_approval(False)
        pump(1500)
        assert "declined" in ctl.last_reply, ctl.last_reply
        assert ctl.state == "listening", ctl.state
        # error path
        ctl.submit("please fail", voice=False)
        pump(1200)
        assert any("model exploded" in e for e in errors), errors
        assert ctl.state == "listening", ctl.state
        # voice commands
        ctl.submit("switch to yui", voice=True)
        pump(300)
        assert ctl.persona == "yui"
        ctl.submit("show the activity", voice=True)
        pump(300)
        assert app.window.activity_dock.isVisible()
        # attention logic through the utterance path
        ctl.bridge.utterance.emit("what time is it")        # not addressed
        pump(300)
        ctl.bridge.utterance.emit("yui")                     # attention only
        pump(300)
        assert ctl.attention.window_open()
        ctl.bridge.utterance.emit("hello again")            # inside window
        pump(1500)
        assert "hello again" in ctl.last_reply, ctl.last_reply
        for style in ("orb", "bars", "ring"):
            app.window.visual.set_style(style)
            app.window.visual.set_state("speaking")
            for i in range(20):
                app.window.visual.set_level(0.08 + 0.05 * (i % 4))
                pump(16)
            shot(f"04-{style}")
        app.window.visual.set_state(ctl.state)
        # settings window
        app.window.open_settings()
        s = app.window._settings
        for i in range(s.nav.count()):
            s.nav.setCurrentRow(i)
            pump(250)
            s.grab().save(str(out / f"05-settings-{i}-{s.nav.item(i).text().lower().replace(' ', '-')}.png"))
        s.close()
        # theme switch
        from genesis_desktop import config
        config.set("theme", "light")
        pump(200)
        shot("06-light")
        config.set("theme", "dark")
        # mute + interrupt
        ctl.set_muted(True)
        assert ctl.state == "muted"
        ctl.set_muted(False)
        ctl.interrupt()
        assert ctl.state == "listening"
        print("SMOKE OK; errors seen:", errors)
    except Exception as e:
        import traceback
        traceback.print_exc()
        shot("99-failure")
        print("SMOKE FAILED:", e, "errors:", errors)
        app._quitting = True
        app.quit()
        os._exit(1)
    app.quit()


QTimer.singleShot(0, run)
sys.exit(app.qt.exec())
