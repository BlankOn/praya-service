#!/bin/bash
# Praya Service Daemon launcher script

set -e

# Import display environment from systemd user session
# This is needed for D-Bus activation to access Wayland/X11 display
if command -v systemctl >/dev/null 2>&1; then
    eval "$(systemctl --user show-environment | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR)=' | sed 's/^/export /')"
fi

PRAYA_DIR="/usr/share/praya"
VENV_DIR="${PRAYA_DIR}/venv"

source "$VENV_DIR/bin/activate"
export PYTHONPATH="${PRAYA_DIR}:${PYTHONPATH}"
exec python3 -m praya.daemon "$@"
