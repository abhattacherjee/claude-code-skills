#!/usr/bin/env bash
set -eu

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] [composition-id]

Render a Remotion video to MP4 and preview it.

Arguments:
  composition-id       Remotion composition ID (auto-detected if only one exists)

Options:
  --output <path>      Output file path (default: out/video.mp4)
  --contact-sheet      Generate a 7-frame contact sheet for visual verification
  --open               Open the rendered video in system player (default: true)
  --no-open            Skip opening the video after render
  --quality <n>        CRF quality 0-63, lower=better (default: Remotion default)
  --frames <list>      Comma-separated frame numbers for contact sheet
                       (default: evenly spaced across video duration)
  -h, --help           Show this help

Examples:
  $(basename "$0")                                    # Auto-detect and render
  $(basename "$0") ProductVideo                       # Render specific composition
  $(basename "$0") --contact-sheet --no-open          # Contact sheet only, no player
  $(basename "$0") --output out/reel-v2.mp4           # Custom output path

EOF
  exit 0
}

COMP_ID=""
OUTPUT="out/video.mp4"
CONTACT_SHEET=false
OPEN_VIDEO=true
QUALITY=""
CUSTOM_FRAMES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --contact-sheet) CONTACT_SHEET=true; shift ;;
    --open) OPEN_VIDEO=true; shift ;;
    --no-open) OPEN_VIDEO=false; shift ;;
    --quality) QUALITY="--crf $2"; shift 2 ;;
    --frames) CUSTOM_FRAMES="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) COMP_ID="$1"; shift ;;
  esac
done

# Auto-detect composition ID if not provided
if [[ -z "$COMP_ID" ]]; then
  # Try to find composition IDs from Root.tsx
  if [[ -f src/Root.tsx ]]; then
    COMP_ID=$(grep -o 'id="[^"]*"' src/Root.tsx | head -1 | sed 's/id="//;s/"//')
  fi
  if [[ -z "$COMP_ID" ]]; then
    echo "Error: Could not auto-detect composition ID. Pass it as an argument." >&2
    exit 1
  fi
  echo "Auto-detected composition: $COMP_ID"
fi

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT")"

# Lint check first
echo "Running lint checks..."
if ! npx eslint src 2>/dev/null; then
  echo "⚠ ESLint errors found. Fix them before rendering." >&2
  exit 1
fi
if ! npx tsc 2>/dev/null; then
  echo "⚠ TypeScript errors found. Fix them before rendering." >&2
  exit 1
fi
echo "✓ Lint passed"

# Render
echo ""
echo "Rendering $COMP_ID → $OUTPUT ..."
npx remotion render "$COMP_ID" "$OUTPUT" $QUALITY

# Show specs
echo ""
echo "=== Video Specs ==="
ffprobe -v error \
  -show_entries format=duration,size \
  -show_entries stream=width,height,codec_name \
  -of default=noprint_wrappers=1 \
  "$OUTPUT" 2>/dev/null | while IFS='=' read -r key val; do
    case "$key" in
      width) echo "  Resolution: ${val}x$(ffprobe -v error -show_entries stream=height -of csv=p=0 "$OUTPUT" 2>/dev/null)" ;;
      duration) printf "  Duration: %.1fs\n" "$val" ;;
      size) echo "  Size: $(echo "$val / 1048576" | bc -l | xargs printf '%.1f') MB" ;;
      codec_name) echo "  Codec: $val" ;;
    esac
  done

# Contact sheet
if $CONTACT_SHEET; then
  SHEET_PATH="${OUTPUT%.mp4}-contact-sheet.png"
  TOTAL_FRAMES=$(ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=nb_read_frames -of csv=p=0 "$OUTPUT" 2>/dev/null || echo "0")

  if [[ -n "$CUSTOM_FRAMES" ]]; then
    # Use custom frame numbers
    SELECT_EXPR=$(echo "$CUSTOM_FRAMES" | tr ',' '\n' | sed 's/^/eq(n\\,/' | sed 's/$/)+/' | tr -d '\n' | sed 's/+$//')
  else
    # Evenly space 7 frames across the video
    if [[ "$TOTAL_FRAMES" -gt 0 ]]; then
      STEP=$((TOTAL_FRAMES / 7))
      SELECT_EXPR="eq(n\\,0)+eq(n\\,$STEP)+eq(n\\,$((STEP*2)))+eq(n\\,$((STEP*3)))+eq(n\\,$((STEP*4)))+eq(n\\,$((STEP*5)))+eq(n\\,$((STEP*6)))"
    else
      SELECT_EXPR="eq(n\\,0)+eq(n\\,100)+eq(n\\,200)+eq(n\\,300)+eq(n\\,400)+eq(n\\,500)+eq(n\\,600)"
    fi
  fi

  echo ""
  echo "Generating contact sheet..."
  ffmpeg -y -i "$OUTPUT" \
    -vf "select='$SELECT_EXPR',scale=154:-1,tile=7x1" \
    -frames:v 1 -update 1 \
    "$SHEET_PATH" 2>/dev/null

  echo "✓ Contact sheet: $SHEET_PATH"
fi

# Open video
if $OPEN_VIDEO; then
  echo ""
  echo "Opening video..."
  open "$OUTPUT"
fi

echo ""
echo "Done! 🎬"
