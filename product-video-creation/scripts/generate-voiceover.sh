#!/usr/bin/env bash
set -eu

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <script-file> <output-dir>

Generate TTS voiceover audio from a narration script.

Options:
  --provider <openai|macos>  TTS provider (default: auto-detect based on OPENAI_API_KEY)
  --voice <name>             Voice name (default: coral for OpenAI, Samantha for macOS)
  --model <model>            OpenAI model (default: gpt-4o-mini-tts)
  --instructions <text>      Voice style instructions for OpenAI TTS
  --speed <n>                Speech speed 0.25-4.0 (default: 0.95)
  --list-voices              List available voices for the selected provider
  -h, --help                 Show this help

Script file format (JSON):
  [
    { "scene": "hook", "text": "What if the hardest part was already done?" },
    { "scene": "intro", "text": "A smarter way to get started." }
  ]

Examples:
  $(basename "$0") narration.json ./public/audio --provider openai --voice coral
  $(basename "$0") narration.json ./public/audio --provider macos --voice Samantha
  $(basename "$0") --list-voices --provider openai

EOF
  exit 0
}

PROVIDER=""
VOICE=""
MODEL="gpt-4o-mini-tts"
INSTRUCTIONS="Speak warmly and calmly. Pause naturally between sentences. Do not rush."
SPEED="0.95"
LIST_VOICES=false
SCRIPT_FILE=""
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --voice) VOICE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --instructions) INSTRUCTIONS="$2"; shift 2 ;;
    --speed) SPEED="$2"; shift 2 ;;
    --list-voices) LIST_VOICES=true; shift ;;
    -h|--help) usage ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *)
      if [[ -z "$SCRIPT_FILE" ]]; then
        SCRIPT_FILE="$1"
      else
        OUTPUT_DIR="$1"
      fi
      shift
      ;;
  esac
done

# Auto-detect provider
if [[ -z "$PROVIDER" ]]; then
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    PROVIDER="openai"
  else
    PROVIDER="macos"
  fi
fi

# Set default voice per provider
if [[ -z "$VOICE" ]]; then
  case "$PROVIDER" in
    openai) VOICE="coral" ;;
    macos) VOICE="Samantha" ;;
  esac
fi

# List voices
if $LIST_VOICES; then
  case "$PROVIDER" in
    openai)
      echo "OpenAI TTS Voices (gpt-4o-mini-tts):"
      echo ""
      echo "  alloy    - Neutral, balanced"
      echo "  ash      - Warm, conversational"
      echo "  ballad   - Soft, melodic"
      echo "  coral    - Clear, warm, natural (recommended)"
      echo "  echo     - Smooth, confident"
      echo "  fable    - Expressive, storytelling"
      echo "  marin    - Bright, friendly"
      echo "  nova     - Energetic, youthful"
      echo "  onyx     - Deep, authoritative"
      echo "  sage     - Calm, wise"
      echo "  shimmer  - Light, airy"
      echo "  verse    - Rich, articulate"
      echo "  cedar    - Warm, grounded"
      ;;
    macos)
      echo "macOS Voices (English):"
      echo ""
      say -v '?' | grep "en_" | awk '{print "  " $1 " (" $2 ")"}'
      ;;
  esac
  exit 0
fi

if [[ -z "$SCRIPT_FILE" || -z "$OUTPUT_DIR" ]]; then
  echo "Error: script file and output directory are required" >&2
  usage
fi

if [[ ! -f "$SCRIPT_FILE" ]]; then
  echo "Error: script file not found: $SCRIPT_FILE" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

case "$PROVIDER" in
  openai)
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
      echo "Error: OPENAI_API_KEY not set." >&2
      echo "Set it with: export OPENAI_API_KEY=sk-..." >&2
      echo "Or use --provider macos for local TTS." >&2
      exit 1
    fi

    # Generate via Node.js script
    GEN_SCRIPT=$(mktemp /tmp/tts-gen-XXXXXX.mjs)
    trap "rm -f $GEN_SCRIPT" EXIT

    cat > "$GEN_SCRIPT" <<SCRIPT
import OpenAI from "openai";
import { readFileSync, writeFileSync } from "fs";

const openai = new OpenAI();
const scenes = JSON.parse(readFileSync("${SCRIPT_FILE}", "utf-8"));
const results = [];

for (let i = 0; i < scenes.length; i++) {
  const scene = scenes[i];
  const padded = String(i + 1).padStart(2, "0");
  const outPath = "${OUTPUT_DIR}/" + padded + "-" + scene.scene + ".mp3";

  console.log("Generating " + padded + "-" + scene.scene + "...");

  const response = await openai.audio.speech.create({
    model: "${MODEL}",
    voice: "${VOICE}",
    input: scene.text,
    instructions: scene.instructions || "${INSTRUCTIONS}",
    response_format: "mp3",
    speed: ${SPEED},
  });

  const buffer = Buffer.from(await response.arrayBuffer());
  writeFileSync(outPath, buffer);

  results.push({ scene: scene.scene, path: outPath, bytes: buffer.length });
  console.log("✓ " + outPath + " (" + Math.round(buffer.length / 1024) + " KB)");
}

console.log("\\nGenerated " + results.length + " audio files.");
SCRIPT

    # Check if openai package is available
    if ! node -e "require('openai')" 2>/dev/null; then
      echo "Installing openai package..."
      npm install --no-save openai 2>/dev/null
    fi

    node "$GEN_SCRIPT"
    ;;

  macos)
    if ! command -v ffmpeg &>/dev/null; then
      echo "Error: ffmpeg required for macOS TTS. Install with: brew install ffmpeg" >&2
      exit 1
    fi

    SCENES=$(cat "$SCRIPT_FILE")
    COUNT=$(echo "$SCENES" | node -e "const d=require('fs').readFileSync('/dev/stdin','utf8');console.log(JSON.parse(d).length)")
    INDEX=0

    echo "$SCENES" | node -e "
      const scenes = JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));
      scenes.forEach((s,i) => console.log(JSON.stringify(s)));
    " | while IFS= read -r line; do
      INDEX=$((INDEX + 1))
      SCENE=$(echo "$line" | node -e "console.log(JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')).scene)")
      TEXT=$(echo "$line" | node -e "console.log(JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')).text)")
      PADDED=$(printf "%02d" "$INDEX")
      AIFF="/tmp/tts-${PADDED}.aiff"
      MP3="${OUTPUT_DIR}/${PADDED}-${SCENE}.mp3"

      echo "Generating ${PADDED}-${SCENE}..."
      say -v "${VOICE}" -o "$AIFF" "$TEXT"
      ffmpeg -y -i "$AIFF" -codec:a libmp3lame -qscale:a 2 "$MP3" 2>/dev/null
      rm -f "$AIFF"
      echo "✓ $MP3"
    done

    echo ""
    echo "Generated audio files with macOS voice: ${VOICE}"
    ;;

  *)
    echo "Unknown provider: $PROVIDER" >&2
    exit 2
    ;;
esac
