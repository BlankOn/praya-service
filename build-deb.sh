#!/bin/bash
# Build Debian package for Praya Posture Service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Building Praya Posture Debian package..."

# Check for build dependencies
if ! command -v dpkg-buildpackage &> /dev/null; then
    echo "Error: dpkg-buildpackage not found."
    echo "Install with: sudo apt install dpkg-dev debhelper"
    exit 1
fi

# Clean previous builds
rm -f ../praya-posture_*.deb ../praya-posture_*.changes ../praya-posture_*.buildinfo
rm -rf debian/praya-posture debian/.debhelper debian/files

# Build the package
dpkg-buildpackage -us -uc -b

# Move the built package
mv ../praya-posture_*.deb ./ 2>/dev/null || true

echo ""
echo "Build complete!"
echo ""
ls -la praya-posture_*.deb 2>/dev/null || echo "Package built in parent directory"
echo ""
echo "Install with: sudo dpkg -i praya-posture_*.deb"
echo "Or with dependencies: sudo apt install ./praya-posture_*.deb"
