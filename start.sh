#!/usr/bin/env bash
#
# start.sh - caphtb installer/launcher
# ------------------------------------
# 1. Creates an isolated virtualenv in ./.venv (does not pollute the system).
# 2. Installs the tool and its dependencies (typer, rich, requests).
# 3. Forwards the arguments to the `caphtb` command.
#
# Usage:
#   ./start.sh                 -> installs and shows the help
#   ./start.sh login           -> configure your token
#   ./start.sh machines        -> list active machines
#   ./start.sh ranking country --country BR
#
set -euo pipefail

# Directory where this script lives, so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"

# Create the virtualenv only on the first run.
if [ ! -d "$VENV_DIR" ]; then
    echo "[*] Creating virtual environment in .venv ..."
    python3 -m venv "$VENV_DIR"
fi

# Activate the virtualenv.
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Install/update the tool quietly (editable mode).
if ! python -c "import caphtb" >/dev/null 2>&1; then
    echo "[*] Installing dependencies and caphtb ..."
    pip install --quiet --upgrade pip
    pip install --quiet -e .
fi

# No arguments: show the help. With arguments: forward them to caphtb.
if [ "$#" -eq 0 ]; then
    caphtb --help
else
    caphtb "$@"
fi
