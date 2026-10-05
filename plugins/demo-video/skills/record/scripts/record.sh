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
ZOOM_MODE=focus
DWELL_THRESHOLD=200
MOVE_THRESHOLD=800

usage() {
    cat <<'HELP'
demo-video:record — Record the screen and the cursor, with optional cursor-following zoom

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
    --zoom-mode MODE       smart-zoom.py mode: focus, click or velocity (default: focus)
    --dwell PIXELS/S       velocity mode only: cursor speed below which it zooms in (default: 200)
    --move PIXELS/S        velocity mode only: cursor speed above which it zooms out (default: 800)
    -h, --help             Show this help

EXAMPLES:
    record.sh                                  # Record until Ctrl+C
    record.sh -d 60 -o ~/Videos               # Record 60 seconds
    record.sh --zoom-max 4.0 --fps 60         # Higher zoom, 60fps
    record.sh --raw-only                       # Just record, skip zoom
    record.sh --zoom-mode velocity --dwell 100 --move 500   # Speed-based zoom

Ctrl+C stops the recording; the video is still saved and processed.
It exits 1 if ffmpeg wrote no video, or (without --raw-only) no cursor log.

OUTPUT FILES:
    {name}.mp4              Zoomed/processed video (main output)
    {name}-raw.mp4          Original full-screen recording
    {name}-cursor.jsonl     Cursor position log (for re-processing)

DEPENDENCIES:
    Run install-deps.sh from the same directory as this script.
HELP
    echo "    (here: $SCRIPT_DIR/install-deps.sh)"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output|-n|--name|-d|--duration|-f|--fps|--zoom-max|--zoom-min|--resolution|--zoom-mode|--dwell|--move)
            if [[ $# -lt 2 ]]; then
                echo "Option $1 needs a value" >&2
                exit 2
            fi ;;
    esac
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
        --zoom-mode) ZOOM_MODE="$2"; shift 2 ;;
        --dwell) DWELL_THRESHOLD="$2"; shift 2 ;;
        --move) MOVE_THRESHOLD="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$ZOOM_MODE" in
    focus|click|velocity) ;;
    *) echo "Unknown --zoom-mode: $ZOOM_MODE (use focus, click or velocity)" >&2; exit 2 ;;
esac

# --- Dependency checks ---
MISSING=0
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "Missing: $1 — $2" >&2
        MISSING=1
    fi
}
check_dep ffmpeg "brew install ffmpeg"
check_dep python3 "install Python 3"
if [[ $MISSING -eq 1 ]]; then
    echo "" >&2
    echo "Install missing dependencies:" >&2
    echo "  $SCRIPT_DIR/install-deps.sh" >&2
    exit 1
fi

if ! python3 -c "from Quartz import CGEventCreate" 2>/dev/null; then
    echo "Missing: pyobjc-framework-Quartz" >&2
    echo "  $SCRIPT_DIR/install-deps.sh" >&2
    exit 1
fi

if [[ "$RAW_ONLY" == false ]]; then
    if ! python3 -c "import cv2" 2>/dev/null; then
        echo "Missing: opencv-python (needed for zoom processing)" >&2
        echo "  $SCRIPT_DIR/install-deps.sh" >&2
        echo "  Or use --raw-only to skip zoom processing" >&2
        exit 1
    fi
fi

# --- Setup ---
# An output directory that starts with "-" would make every path below read as an option.
case "$OUTPUT_DIR" in -*) OUTPUT_DIR="./$OUTPUT_DIR" ;; esac
mkdir -p -- "$OUTPUT_DIR"

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

echo "=== Demo Video (record) ==="
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

# Ctrl+C (SIGINT) is how the user stops the recording. Without a trap the shell
# would die inside `wait` below, and never remux or process the video. The trap
# passes the stop on to ffmpeg, which finishes its file, and the script carries on.
STOP_REQUESTED=false
on_stop() {
    STOP_REQUESTED=true
    if [[ -n "$FFMPEG_PID" ]]; then
        kill -INT "$FFMPEG_PID" 2>/dev/null || true
    fi
}
trap on_stop INT TERM

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
if $STOP_REQUESTED; then
    kill -INT "$FFMPEG_PID" 2>/dev/null || true
fi

# Wait for ffmpeg to finish (Ctrl+C or duration limit). A trapped signal ends
# `wait` early, so wait again until ffmpeg has really exited.
while kill -0 "$FFMPEG_PID" 2>/dev/null; do
    WAIT_RC=0
    wait "$FFMPEG_PID" 2>/dev/null || WAIT_RC=$?
    [[ "$WAIT_RC" -eq 127 ]] && break  # not our child any more
done
FFMPEG_PID=""
# A second Ctrl+C from here on stops the script as usual.
trap - INT TERM

echo ""
echo "  Recording stopped."

if [[ ! -s "$MKV_FILE" ]]; then
    echo "Error: ffmpeg wrote no video ($MKV_FILE is missing or empty)." >&2
    echo "  Check the ffmpeg message above, and that Terminal has Screen Recording permission." >&2
    exit 1
fi

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

# The cursor log needs more than its header line to drive the zoom.
if [[ "$RAW_ONLY" == false ]] && [[ "$(grep -c . "$CURSOR_FILE" 2>/dev/null || true)" -lt 2 ]]; then
    echo "Error: the cursor tracker wrote no positions to $CURSOR_FILE, so the zoom cannot run." >&2
    echo "  The raw recording is kept: $RAW_FILE" >&2
    echo "  Check the tracker message above (pyobjc, Accessibility permission)." >&2
    exit 1
fi

# --- Post-process with smart zoom ---
if [[ "$RAW_ONLY" == false ]]; then
    echo ""
    echo "  Post-processing with smart zoom ($ZOOM_MODE mode)..."
    if ! python3 "$SCRIPT_DIR/smart-zoom.py" \
        "$RAW_FILE" "$CURSOR_FILE" \
        -o "$OUTPUT_FILE" \
        --mode "$ZOOM_MODE" \
        --zoom-min "$ZOOM_MIN" \
        --zoom-max "$ZOOM_MAX" \
        --resolution "$OUTPUT_RES" \
        --dwell-threshold "$DWELL_THRESHOLD" \
        --move-threshold "$MOVE_THRESHOLD"; then
        echo "Error: zoom processing failed. The raw recording is kept: $RAW_FILE" >&2
        exit 1
    fi

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
