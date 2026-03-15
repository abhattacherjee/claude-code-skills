#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$HOME/Desktop"
OUTPUT_NAME="screen-recording-$(date +%Y%m%d-%H%M%S)"
FPS=30
DURATION=""
ZOOM_MAX=3.0
ZOOM_MIN=1.0
OUTPUT_RES="1920x1080"
RAW_ONLY=false
DWELL_THRESHOLD=200
MOVE_THRESHOLD=800

usage() {
    cat <<'HELP'
Smart Screen Recorder — Record with intelligent cursor-following zoom

USAGE:
    record.sh [OPTIONS]

OPTIONS:
    -o, --output DIR       Output directory (default: ~/Desktop)
    -n, --name NAME        Output filename stem (default: timestamped)
    -d, --duration SECS    Max recording duration (default: until Ctrl+C)
    -f, --fps FPS          Frame rate (default: 30)
    --zoom-max FLOAT       Maximum zoom level (default: 3.0)
    --zoom-min FLOAT       Minimum zoom level (default: 1.0)
    --resolution WxH       Output resolution (default: 1920x1080)
    --raw-only             Save raw recording without zoom processing
    --dwell PIXELS/S       Cursor speed to trigger zoom-in (default: 200)
    --move PIXELS/S        Cursor speed to trigger zoom-out (default: 800)
    -h, --help             Show this help

EXAMPLES:
    record.sh                                  # Record until Ctrl+C
    record.sh -d 60 -o ~/Videos               # Record 60 seconds
    record.sh --zoom-max 4.0 --fps 60         # Higher zoom, 60fps
    record.sh --raw-only                       # Just record, skip zoom
    record.sh --dwell 100 --move 500          # More aggressive zoom

OUTPUT FILES:
    {name}.mp4              Zoomed/processed video (main output)
    {name}-raw.mp4          Original full-screen recording
    {name}-cursor.jsonl     Cursor position log (for re-processing)

DEPENDENCIES:
    Run: ~/.claude/skills/smart-screen-recorder/scripts/install-deps.sh
HELP
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        -o|--output) OUTPUT_DIR="$2"; shift 2 ;;
        -n|--name) OUTPUT_NAME="$2"; shift 2 ;;
        -d|--duration) DURATION="$2"; shift 2 ;;
        -f|--fps) FPS="$2"; shift 2 ;;
        --zoom-max) ZOOM_MAX="$2"; shift 2 ;;
        --zoom-min) ZOOM_MIN="$2"; shift 2 ;;
        --resolution) OUTPUT_RES="$2"; shift 2 ;;
        --raw-only) RAW_ONLY=true; shift ;;
        --dwell) DWELL_THRESHOLD="$2"; shift 2 ;;
        --move) MOVE_THRESHOLD="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; usage; exit 2 ;;
    esac
done

# --- Dependency checks ---
MISSING=0
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "Missing: $1 — $2"
        MISSING=1
    fi
}
check_dep ffmpeg "brew install ffmpeg"
check_dep python3 "install Python 3"
if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "Install missing dependencies:"
    echo "  $SCRIPT_DIR/install-deps.sh"
    exit 1
fi

if ! python3 -c "from Quartz import CGEventCreate" 2>/dev/null; then
    echo "Missing: pyobjc-framework-Quartz"
    echo "  pip3 install pyobjc-framework-Quartz"
    exit 1
fi

if [[ "$RAW_ONLY" == false ]]; then
    if ! python3 -c "import cv2" 2>/dev/null; then
        echo "Missing: opencv-python (needed for zoom processing)"
        echo "  pip3 install opencv-python"
        echo "  Or use --raw-only to skip zoom processing"
        exit 1
    fi
fi

# --- Setup ---
mkdir -p "$OUTPUT_DIR"

RAW_FILE="$OUTPUT_DIR/${OUTPUT_NAME}-raw.mp4"
CURSOR_FILE="$OUTPUT_DIR/${OUTPUT_NAME}-cursor.jsonl"
OUTPUT_FILE="$OUTPUT_DIR/${OUTPUT_NAME}.mp4"

# Auto-detect screen capture device index
SCREEN_INDEX=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 \
    | grep "Capture screen 0" \
    | grep -oE '\[([0-9]+)\]' \
    | head -1 \
    | tr -d '[]' || true)

if [[ -z "$SCREEN_INDEX" ]]; then
    echo "Warning: Could not detect screen device, trying index 1"
    SCREEN_INDEX=1
fi

echo "=== Smart Screen Recorder ==="
echo "  Output:     $OUTPUT_DIR/$OUTPUT_NAME.*"
echo "  FPS:        $FPS"
echo "  Resolution: $OUTPUT_RES"
echo "  Zoom:       ${ZOOM_MIN}x — ${ZOOM_MAX}x"
echo "  Screen:     device $SCREEN_INDEX"
echo ""
echo "  Press Ctrl+C to stop recording"
echo ""

# --- Build ffmpeg args ---
DURATION_ARGS=()
if [[ -n "$DURATION" ]]; then
    DURATION_ARGS=(-t "$DURATION")
fi

# --- Start recording ---

# Track PIDs for cleanup
FFMPEG_PID=""
TRACKER_PID=""

cleanup() {
    # Stop cursor tracker
    if [[ -n "$TRACKER_PID" ]] && kill -0 "$TRACKER_PID" 2>/dev/null; then
        kill -TERM "$TRACKER_PID" 2>/dev/null || true
        wait "$TRACKER_PID" 2>/dev/null || true
    fi
    # Stop ffmpeg (if still running)
    if [[ -n "$FFMPEG_PID" ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
        kill -INT "$FFMPEG_PID" 2>/dev/null || true
        wait "$FFMPEG_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Start cursor tracker in background
python3 "$SCRIPT_DIR/cursor-tracker.py" -o "$CURSOR_FILE" -f "$FPS" &
TRACKER_PID=$!

# Record to MKV first — MKV writes metadata incrementally so it survives interruption.
# MP4 writes the moov atom at the end, so a killed process = corrupted file.
MKV_FILE="${RAW_FILE%.mp4}.mkv"

# Start ffmpeg screen recording
ffmpeg -y -hide_banner -loglevel error \
    -f avfoundation \
    -capture_cursor 1 \
    -framerate "$FPS" \
    -pixel_format nv12 \
    -i "${SCREEN_INDEX}:none" \
    "${DURATION_ARGS[@]+"${DURATION_ARGS[@]}"}" \
    -c:v libx264 -preset ultrafast -crf 18 \
    "$MKV_FILE" &
FFMPEG_PID=$!

# Wait for ffmpeg to finish (Ctrl+C or duration limit)
wait "$FFMPEG_PID" 2>/dev/null || true
FFMPEG_PID=""

echo ""
echo "  Recording stopped."

# Remux MKV to MP4 (fast, no re-encoding)
if [[ -f "$MKV_FILE" ]]; then
    echo "  Remuxing to MP4..."
    ffmpeg -y -hide_banner -loglevel error \
        -i "$MKV_FILE" \
        -c copy -movflags +faststart \
        "$RAW_FILE" 2>/dev/null && rm -f "$MKV_FILE" || {
        echo "  Remux failed, keeping MKV: $MKV_FILE"
        RAW_FILE="$MKV_FILE"
    }
fi

# Give tracker a moment to flush final positions, then stop it
sleep 0.3
if [[ -n "$TRACKER_PID" ]] && kill -0 "$TRACKER_PID" 2>/dev/null; then
    kill -TERM "$TRACKER_PID" 2>/dev/null || true
    wait "$TRACKER_PID" 2>/dev/null || true
fi
TRACKER_PID=""

echo "  Raw recording: $RAW_FILE"
echo "  Cursor log:    $CURSOR_FILE"

# --- Post-process with smart zoom ---
if [[ "$RAW_ONLY" == false ]] && [[ -f "$RAW_FILE" ]] && [[ -f "$CURSOR_FILE" ]]; then
    echo ""
    echo "  Post-processing with smart zoom..."
    python3 "$SCRIPT_DIR/smart-zoom.py" \
        "$RAW_FILE" "$CURSOR_FILE" \
        -o "$OUTPUT_FILE" \
        --zoom-min "$ZOOM_MIN" \
        --zoom-max "$ZOOM_MAX" \
        --resolution "$OUTPUT_RES" \
        --dwell-threshold "$DWELL_THRESHOLD" \
        --move-threshold "$MOVE_THRESHOLD"

    echo ""
    echo "=== Recording complete ==="
    echo "  Zoomed:  $OUTPUT_FILE"
    echo "  Raw:     $RAW_FILE"
    echo "  Cursor:  $CURSOR_FILE"
    echo ""
    echo "  Re-process with different settings:"
    echo "    python3 $SCRIPT_DIR/smart-zoom.py $RAW_FILE $CURSOR_FILE -o output.mp4 --zoom-max 5.0"
else
    echo ""
    echo "=== Recording complete (raw only) ==="
    echo "  Raw:     $RAW_FILE"
    echo "  Cursor:  $CURSOR_FILE"
fi
