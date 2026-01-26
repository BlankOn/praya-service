#!/bin/bash
# Quick run script for development/testing

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv --system-site-packages venv

    echo "Installing Python dependencies..."
    source venv/bin/activate
    pip install opencv-python mediapipe
else
    source venv/bin/activate
fi

# Check dependencies
check_dep() {
    python3 -c "import $1" 2>/dev/null || {
        echo "Missing: $1"
        return 1
    }
}

missing=0
echo "Checking dependencies..."

if ! check_dep "gi"; then
    echo "  - PyGObject (python3-gi) is required"
    echo "    On Debian/Ubuntu: sudo apt install python3-gi python3-gi-cairo"
    missing=1
fi

if ! check_dep "cv2"; then
    echo "  - OpenCV is missing, installing..."
    pip install opencv-python
fi

if ! check_dep "mediapipe"; then
    echo "  - MediaPipe is missing, installing..."
    pip install mediapipe
fi

# Check GTK4 and Adwaita
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')" 2>/dev/null || {
    echo "  - GTK4 and libadwaita GObject introspection bindings required"
    echo "    On Debian/Ubuntu: sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1"
    missing=1
}

if [ $missing -eq 1 ]; then
    echo ""
    echo "Please install missing system dependencies and try again."
    exit 1
fi

echo "All dependencies found."
echo ""
echo "Starting Praya Posture Service..."
echo "  - Press Escape during calibration to skip"
echo "  - Press Ctrl+C to quit"
echo ""

export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"
exec python3 -m praya.services.posture "$@"
