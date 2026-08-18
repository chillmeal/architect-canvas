#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python}

"$PYTHON_BIN" "$ROOT_DIR/scripts/generate_openapi_snapshot.py"
"$PYTHON_BIN" "$ROOT_DIR/scripts/generate_ts_client.py"
