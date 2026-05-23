#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV_DIR="$PROJECT_DIR/.venv-build"
PYTHON_BIN="${PYTHON:-python3}"
APP_NAME="ZTE Traffic Alert"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This script must be run on macOS to build a .app bundle."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python" -c "import PyInstaller" >/dev/null 2>&1; then
  # Optional: pass extra pip args with PIP_EXTRA_ARGS, for example:
  # PIP_EXTRA_ARGS="--trusted-host pypi.org --trusted-host files.pythonhosted.org"
  "$VENV_DIR/bin/python" -m pip install ${PIP_EXTRA_ARGS:-} --upgrade pip pyinstaller
fi

cd "$PROJECT_DIR"
"$VENV_DIR/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --add-data "config.example.json:." \
  zte_traffic_alert_gui.py

echo "Built: $PROJECT_DIR/dist/$APP_NAME.app"
