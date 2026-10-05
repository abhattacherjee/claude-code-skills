#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'HELP'
Install the dependencies for demo-video:record: ffmpeg, python3 (checked),
pyobjc-framework-Quartz, opencv-python and numpy.

USAGE:
    install-deps.sh [-h|--help]

It installs ffmpeg with Homebrew and the Python packages with pip3. Anything
already installed is left alone. macOS only.
HELP
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

echo "=== Demo Video (record) — Dependency Installer ==="
echo ""

# ffmpeg
if command -v ffmpeg &>/dev/null; then
    echo "  ffmpeg:                    installed ($(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3))"
else
    echo "  ffmpeg:                    installing via Homebrew..."
    if command -v brew &>/dev/null; then
        brew install ffmpeg
    else
        echo "  Error: Homebrew not found. Install ffmpeg manually: https://ffmpeg.org"
        exit 1
    fi
fi

# Python 3
if command -v python3 &>/dev/null; then
    echo "  python3:                   installed ($(python3 --version 2>&1 | cut -d' ' -f2))"
else
    echo "  Error: Python 3 not found. Install via: brew install python3"
    exit 1
fi

# pyobjc-framework-Quartz
if python3 -c "from Quartz import CGEventCreate" 2>/dev/null; then
    echo "  pyobjc-framework-Quartz:   installed"
else
    echo "  pyobjc-framework-Quartz:   installing..."
    pip3 install pyobjc-framework-Quartz
fi

# opencv-python
if python3 -c "import cv2" 2>/dev/null; then
    echo "  opencv-python:             installed"
else
    echo "  opencv-python:             installing..."
    pip3 install opencv-python
fi

# numpy (typically installed with opencv, but check)
if python3 -c "import numpy" 2>/dev/null; then
    echo "  numpy:                     installed"
else
    echo "  numpy:                     installing..."
    pip3 install numpy
fi

echo ""
echo "All dependencies installed."
echo ""
echo "Usage:"
echo "  $SCRIPT_DIR/record.sh"
echo "  $SCRIPT_DIR/record.sh --help"
echo ""
echo "Note: macOS will prompt for Screen Recording permission on first use."
echo "Grant it in: System Settings > Privacy & Security > Screen & System Audio Recording"
