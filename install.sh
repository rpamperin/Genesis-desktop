#!/usr/bin/env bash
# Install Genesis Desktop on Ubuntu into a virtualenv, with a launcher.
#
#   ./install.sh            everything: system libs (sudo), venv, voice models
#   ./install.sh --no-sudo  skip apt; you install libportaudio2 etc. yourself
#   ./install.sh --no-models  skip the Vosk and Piper downloads
set -euo pipefail
cd "$(dirname "$0")"

SUDO=1; MODELS=1
for a in "$@"; do
  case "$a" in
    --no-sudo) SUDO=0 ;;
    --no-models) MODELS=0 ;;
  esac
done

if [ "$SUDO" = 1 ] && command -v apt-get >/dev/null; then
  echo "== system packages"
  sudo apt-get install -y python3-venv python3-pip libportaudio2 libxcb-cursor0 \
    espeak-ng policykit-1 libnotify-bin pulseaudio-utils xdg-utils
fi

echo "== python environment"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip wheel >/dev/null
pip install -e . 
pip install vosk piper-tts || echo "   (voice extras failed to install; the app still runs with espeak-ng)"

if [ "$MODELS" = 1 ]; then
  echo "== voice models (offline speech recognition + a Piper voice for each persona)"
  python - <<'PY'
from genesis_desktop import config
from genesis_desktop.voice import stt, tts
config.ensure_dirs()
try:
    if not stt.vosk_ready()[0]:
        print("   downloading Vosk model...")
        stt.download_vosk_model()
except Exception as e:
    print("   vosk model download failed:", e)
for v in ("en_GB-alan-medium", "en_US-amy-medium"):
    try:
        if not tts.piper_voice_paths(v)[0].exists():
            print("   downloading Piper voice", v, "...")
            tts.download_piper_voice(v)
    except Exception as e:
        print("   voice download failed:", v, e)
PY
fi

echo "== launcher"
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps ~/.local/bin
cp genesis_desktop/resources/genesis-desktop.svg ~/.local/share/icons/hicolor/scalable/apps/
sed "s|^Exec=.*|Exec=$(pwd)/.venv/bin/genesis-desktop|" genesis-desktop.desktop > ~/.local/share/applications/genesis-desktop.desktop
ln -sf "$(pwd)/.venv/bin/genesis-desktop" ~/.local/bin/genesis-desktop
update-desktop-database ~/.local/share/applications 2>/dev/null || true

echo
echo "Installed. Run:  genesis-desktop      (or find Genesis in your app menu)"
echo "First run: Settings > Connection and point it at your backend."
.venv/bin/genesis-desktop --doctor || true
