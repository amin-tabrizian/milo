#!/bin/zsh
# Start Milo on this Mac and print how to reach it from your phone.
set -e
cd "${0:A:h}"
command -v whisper-server >/dev/null || { echo "Installing whisper.cpp and ffmpeg..."; brew install whisper-cpp ffmpeg; }
MODEL=models/ggml-large-v3-turbo-q5_0.bin
if [[ ! -f $MODEL ]]; then
  mkdir -p models
  echo "Downloading Whisper model (~550 MB)..."
  curl -fL -o $MODEL https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
fi
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [[ ! -f models/$f ]]; then
    echo "Downloading natural voice ($f)..."
    curl -fL -o models/$f https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f
  fi
done
uv sync -q
# Milo has its own Claude profile, so its memory and settings stay apart from your other Claude sessions
CLAUDE_DIR=${MILO_CLAUDE_DIR:-$PWD/data/claude}
if ! CLAUDE_CONFIG_DIR=$CLAUDE_DIR claude auth status >/dev/null 2>&1; then
  echo "Sign in to Claude for Milo (its own profile, apart from your other Claude sessions)..."
  CLAUDE_CONFIG_DIR=$CLAUDE_DIR claude auth login
fi
PORT=$(uv run -q python -c 'import json;print(json.load(open("data/config.json")).get("port",8765))' 2>/dev/null || echo 8765)

if command -v tailscale >/dev/null && tailscale status >/dev/null 2>&1; then
  tailscale serve --bg --https=443 "http://127.0.0.1:$PORT" >/dev/null
  HOST=$(tailscale status --json | uv run -q python -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
  URL="https://$HOST"
else
  URL="http://127.0.0.1:$PORT (Tailscale not running: phone access is off)"
fi

uv run -q python -c 'import server' >/dev/null 2>&1 || true
TOKEN=$(uv run -q python -c 'import json;print(json.load(open("data/config.json"))["token"])')
echo
echo "  Milo"
echo "  Phone URL : $URL"
echo "  Token     : $TOKEN"
echo "  One-tap   : $URL/#token=$TOKEN   (open in Safari, then Share > Add to Home Screen)"
echo
exec uv run python server.py
