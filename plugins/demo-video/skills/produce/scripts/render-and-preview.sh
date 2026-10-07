#!/usr/bin/env bash
set -eu

usage() {
  local rc="${1:-0}"
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] [composition-id]

Render a Remotion video to MP4 and preview it. Run it from the Remotion
project directory, after npm install.

Arguments:
  composition-id       Remotion composition ID. Optional when src/Root.tsx has
                       exactly one; required when it has several.

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
  exit "$rc"
}

COMP_ID=""
OUTPUT="out/video.mp4"
CONTACT_SHEET=false
OPEN_VIDEO=true
QUALITY=""
CUSTOM_FRAMES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output|--quality|--frames)
      if [[ $# -lt 2 ]]; then
        echo "Option $1 needs a value" >&2
        exit 2
      fi ;;
  esac
  case "$1" in
    --output) OUTPUT="$2"; shift 2 ;;
    --contact-sheet) CONTACT_SHEET=true; shift ;;
    --open) OPEN_VIDEO=true; shift ;;
    --no-open) OPEN_VIDEO=false; shift ;;
    --quality) QUALITY="--crf $2"; shift 2 ;;
    --frames) CUSTOM_FRAMES="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) COMP_ID="$1"; shift ;;
  esac
done

# Auto-detect the composition ID when there is exactly one in src/Root.tsx
if [[ -z "$COMP_ID" ]]; then
  IDS=""
  if [[ -f src/Root.tsx ]]; then
    IDS=$(grep -o 'id="[^"]*"' src/Root.tsx | sed 's/id="//;s/"//' | sort -u || true)
  fi
  N_IDS=$(printf '%s' "$IDS" | grep -c . || true)
  if [[ "$N_IDS" -eq 0 ]]; then
    echo "Error: Could not auto-detect composition ID. Pass it as an argument." >&2
    exit 1
  fi
  if [[ "$N_IDS" -gt 1 ]]; then
    echo "Error: src/Root.tsx has $N_IDS compositions: $(printf '%s' "$IDS" | tr '\n' ' ')" >&2
    echo "Pass the one to render as an argument." >&2
    exit 1
  fi
  COMP_ID="$IDS"
  echo "Auto-detected composition: $COMP_ID"
fi

# An --output that starts with "-" would be read as an option by dirname, ffprobe and ffmpeg.
case "$OUTPUT" in -*) OUTPUT="./$OUTPUT" ;; esac

# Ensure output directory exists
mkdir -p -- "$(dirname -- "$OUTPUT")"

# Lint check first. Run the project's own eslint and tsc, so a missing one is
# reported as missing, not as lint errors, and npx never downloads anything.
echo "Running lint checks..."
for tool in eslint tsc; do
  if [[ ! -x "node_modules/.bin/$tool" ]]; then
    echo "Error: $tool is not installed in this project (no node_modules/.bin/$tool)." >&2
    echo "Run npm install in the project directory first." >&2
    exit 1
  fi
done
LINT_RC=0
node_modules/.bin/eslint src || LINT_RC=$?
if [[ "$LINT_RC" -eq 1 ]]; then
  echo "⚠ ESLint errors found. Fix them before rendering." >&2
  exit 1
elif [[ "$LINT_RC" -ne 0 ]]; then
  echo "Error: ESLint could not run (exit $LINT_RC): a config problem or a crash, see above." >&2
  exit 1
fi
TSC_RC=0
node_modules/.bin/tsc || TSC_RC=$?
if [[ "$TSC_RC" -eq 1 || "$TSC_RC" -eq 2 ]]; then
  echo "⚠ TypeScript errors found. Fix them before rendering." >&2
  exit 1
elif [[ "$TSC_RC" -ne 0 ]]; then
  echo "Error: tsc could not run (exit $TSC_RC), see above." >&2
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
  if ! FF_OUT=$(ffmpeg -y -i "$OUTPUT" \
    -vf "select='$SELECT_EXPR',scale=154:-1,tile=7x1" \
    -frames:v 1 -update 1 \
    "$SHEET_PATH" 2>&1); then
    printf '%s\n' "$FF_OUT" | tail -n 5 >&2
    echo "Error: the contact sheet failed (ffmpeg, see above). The video is at $OUTPUT" >&2
    exit 1
  fi

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
