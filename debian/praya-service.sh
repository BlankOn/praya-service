#!/bin/bash
# Praya Service Daemon launcher script
# Manages virtual environment and runs the daemon

set -e

# Import display environment from systemd user session
# This is needed for D-Bus activation to access Wayland/X11 display
if command -v systemctl >/dev/null 2>&1; then
    eval "$(systemctl --user show-environment | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR)=' | sed 's/^/export /')"
fi

PRAYA_DIR="/usr/share/praya"
VENV_DIR="${HOME}/.local/share/praya/venv"
REQUIREMENTS="${PRAYA_DIR}/requirements.txt"

# Create venv if it doesn't exist
setup_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Setting up Praya for first use..."
        mkdir -p "$(dirname "$VENV_DIR")"
        python3 -m venv --system-site-packages "$VENV_DIR"

        source "$VENV_DIR/bin/activate"
        pip install --quiet --upgrade pip
        pip install --quiet -r "$REQUIREMENTS"

        echo "Setup complete!"
    fi
}

# Check if venv needs updating (requirements changed)
check_requirements() {
    local marker="${VENV_DIR}/.requirements_hash"
    local current_hash=$(md5sum "$REQUIREMENTS" | cut -d' ' -f1)

    if [ -f "$marker" ]; then
        local stored_hash=$(cat "$marker")
        if [ "$current_hash" != "$stored_hash" ]; then
            echo "Updating dependencies..."
            source "$VENV_DIR/bin/activate"
            pip install --quiet -r "$REQUIREMENTS"
            echo "$current_hash" > "$marker"
        fi
    else
        echo "$current_hash" > "$marker"
    fi
}

# Main
setup_venv
check_requirements

source "$VENV_DIR/bin/activate"
export PYTHONPATH="${PRAYA_DIR}:${PYTHONPATH}"
exec python3 -m praya.daemon "$@"
