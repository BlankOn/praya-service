#!/bin/bash
# Praya Linux - Installation Script (for development/manual install)

set -e

echo "Installing Praya Posture Service..."

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Detect package manager and install system dependencies
install_system_deps() {
    if command -v apt &> /dev/null; then
        echo "Installing system dependencies via apt..."
        sudo apt update
        sudo apt install -y \
            python3-pip \
            python3-gi \
            python3-gi-cairo \
            gir1.2-gtk-4.0 \
            gir1.2-adw-1 \
            gir1.2-notify-0.7 \
            libgirepository1.0-dev \
            libcairo2-dev \
            pkg-config \
            python3-dev
    elif command -v dnf &> /dev/null; then
        echo "Installing system dependencies via dnf..."
        sudo dnf install -y \
            python3-pip \
            python3-gobject \
            gtk4 \
            libadwaita \
            libnotify \
            gobject-introspection-devel \
            cairo-devel \
            pkg-config \
            python3-devel
    elif command -v pacman &> /dev/null; then
        echo "Installing system dependencies via pacman..."
        sudo pacman -S --noconfirm \
            python-pip \
            python-gobject \
            gtk4 \
            libadwaita \
            libnotify \
            gobject-introspection \
            cairo \
            pkgconf
    else
        echo "Warning: Could not detect package manager."
        echo "Please manually install: GTK4, libadwaita, PyGObject, libnotify."
    fi
}

# Install system dependencies
install_system_deps

# Create directories
APP_DIR="${HOME}/.local/share/praya"
VENV_DIR="${APP_DIR}/venv"
mkdir -p "$APP_DIR"

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR" --system-site-packages
fi

# Activate and install Python dependencies
echo "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install opencv-python mediapipe

# Copy application
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SCRIPT_DIR/praya" "$APP_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/"

# Create launcher script
mkdir -p "${HOME}/.local/bin"
cat > "${HOME}/.local/bin/praya-posture" << 'EOF'
#!/bin/bash
source "${HOME}/.local/share/praya/venv/bin/activate"
export PYTHONPATH="${HOME}/.local/share/praya:${PYTHONPATH}"
exec python3 -m praya.services.posture "$@"
EOF
chmod +x "${HOME}/.local/bin/praya-posture"

# Create desktop entry
mkdir -p "${HOME}/.local/share/applications"
cat > "${HOME}/.local/share/applications/praya-posture.desktop" << EOF
[Desktop Entry]
Name=Praya Posture
Comment=Posture monitoring service
Exec=${HOME}/.local/bin/praya-posture
Icon=camera-web
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=false
EOF

# Create systemd user service
mkdir -p "${HOME}/.config/systemd/user"
cat > "${HOME}/.config/systemd/user/praya-posture.service" << EOF
[Unit]
Description=Praya Posture Service - Posture monitoring
After=graphical-session.target

[Service]
Type=simple
ExecStart=${HOME}/.local/bin/praya-posture
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

echo ""
echo "Installation complete!"
echo ""
echo "You can now run Praya Posture by:"
echo "  1. Running 'praya-posture' from terminal (add ~/.local/bin to PATH if needed)"
echo "  2. Searching for 'Praya Posture' in your application menu"
echo ""
echo "To run as a service:"
echo "  systemctl --user start praya-posture    # Start now"
echo "  systemctl --user enable praya-posture   # Enable on login"
echo ""
