#!/usr/bin/env bash
#
# download.sh - convenience wrapper around music_downloader.py.
#
# It activates the project's virtual environment (creating it if necessary)
# and forwards every argument to the Python script. This means you can run:
#
#     ./download.sh -s "some song name"
#
# without worrying about which Python/pip is being used.
#
set -euo pipefail

# Move to the directory this script lives in so relative paths work.
cd "$(dirname "$0")"

VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"

# Create the virtual environment + install deps the first time.
if [ ! -x "$VENV_PY" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_PY" -m pip install --upgrade pip -q
    "$VENV_PY" -m pip install -q -r requirements.txt
    echo "Environment ready."
fi

exec "$VENV_PY" music_downloader.py "$@"
