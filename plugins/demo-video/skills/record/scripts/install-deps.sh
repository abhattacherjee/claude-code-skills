#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'HELP'
Install the dependencies for demo-video:record: ffmpeg, python3 (checked),
pyobjc-framework-Quartz, opencv-python and numpy.

USAGE:
    install-deps.sh [-h|--help]

It installs ffmpeg with Homebrew and the Python packages with
`python3 -m pip`, into the same python3 that runs the scripts. Anything already
installed is left alone. At the end it checks every import again and exits 1 if
one still fails. macOS only.
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
        echo "  Error: Homebrew not found. Install ffmpeg manually: https://ffmpeg.org" >&2
        exit 1
    fi
fi

# Python 3
if command -v python3 &>/dev/null; then
    echo "  python3:                   installed ($(python3 --version 2>&1 | cut -d' ' -f2))"
else
    echo "  Error: Python 3 not found. Install via: brew install python3" >&2
    exit 1
fi

# pip_install <package>: install into the python3 on PATH. A Python managed by
# Homebrew or the OS refuses (PEP 668, "externally-managed-environment"); say how
# to get past that instead of showing pip's long error alone.
pip_install() {
    local out
    if out=$(python3 -m pip install "$1" 2>&1); then
        printf '%s\n' "$out" | tail -n 1
        return 0
    fi
    printf '%s\n' "$out" | tail -n 5 >&2
    if printf '%s' "$out" | grep -q "externally-managed-environment"; then
        cat >&2 <<MSG

  Error: this python3 ($(command -v python3)) is managed by Homebrew or the OS,
  so pip will not install $1 into it (PEP 668). Either:
    - use a virtual environment, then run this script again from it:
        python3 -m venv ~/.venvs/demo-video
        source ~/.venvs/demo-video/bin/activate
    - or install for your user only:
        python3 -m pip install --user $1
MSG
    else
        echo "  Error: python3 -m pip install $1 failed (see above)." >&2
    fi
    exit 1
}

# module_ok <import statement>
module_ok() { python3 -c "$1" 2>/dev/null; }

# pyobjc-framework-Quartz
if module_ok "from Quartz import CGEventCreate"; then
    echo "  pyobjc-framework-Quartz:   installed"
else
    echo "  pyobjc-framework-Quartz:   installing..."
    pip_install pyobjc-framework-Quartz
fi

# opencv-python
if module_ok "import cv2"; then
    echo "  opencv-python:             installed"
else
    echo "  opencv-python:             installing..."
    pip_install opencv-python
fi

# numpy (typically installed with opencv, but check)
if module_ok "import numpy"; then
    echo "  numpy:                     installed"
else
    echo "  numpy:                     installing..."
    pip_install numpy
fi

# Check again: an install can "succeed" into another Python than the python3 on PATH.
FAILED=""
command -v ffmpeg &>/dev/null || FAILED="$FAILED ffmpeg"
module_ok "from Quartz import CGEventCreate" || FAILED="$FAILED pyobjc-framework-Quartz"
module_ok "import cv2" || FAILED="$FAILED opencv-python"
module_ok "import numpy" || FAILED="$FAILED numpy"
if [[ -n "$FAILED" ]]; then
    echo "" >&2
    echo "  Error: still missing after the install:$FAILED" >&2
    echo "  python3 here is $(command -v python3). Check that pip installed into it." >&2
    exit 1
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
