#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

"$PYTHON_BIN" -m venv "$ROOT_DIR/.venv"

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
elif [ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]; then
  VENV_PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
else
  echo "Unable to locate Python executable in .venv" >&2
  exit 1
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e "$ROOT_DIR/apps/api[dev]"

cd "$ROOT_DIR"
npm install
