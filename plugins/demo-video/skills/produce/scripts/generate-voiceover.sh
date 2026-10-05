#!/usr/bin/env bash
set -eu

usage() {
  local rc="${1:-0}"
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <script-file> <output-dir>

Generate TTS voiceover audio from a narration script.
Run it from your project directory: the openai package is loaded (and, if
missing, installed with npm) there.

Options:
  --provider <openai|macos>  TTS provider (default: openai if OPENAI_API_KEY is set, else macos)
  --voice <name>             Voice name (default: coral for OpenAI, Samantha for macOS)
  --model <model>            OpenAI model (default: gpt-4o-mini-tts)
  --instructions <text>      Voice style instructions for OpenAI TTS
  --speed <n>                Speech speed 0.25-4.0 (default: 0.95)
  --list-voices              List available voices for the selected provider
  -h, --help                 Show this help

Script file format (JSON array; every scene needs a non-empty "text"):
  [
    { "scene": "hook", "text": "What if the hardest part was already done?" },
    { "scene": "intro", "text": "A smarter way to get started." }
  ]
Each file is named NN-<scene>.mp3. Characters other than letters, digits,
"_" and "-" in the scene name become "-".

Examples:
  $(basename "$0") narration.json ./public/audio --provider openai --voice coral
  $(basename "$0") narration.json ./public/audio --provider macos --voice Samantha
  $(basename "$0") --list-voices --provider openai

EOF
  exit "$rc"
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
    --provider|--voice|--model|--instructions|--speed)
      if [[ $# -lt 2 ]]; then
        echo "Option $1 needs a value" >&2
        exit 2
      fi ;;
  esac
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --voice) VOICE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --instructions) INSTRUCTIONS="$2"; shift 2 ;;
    --speed) SPEED="$2"; shift 2 ;;
    --list-voices) LIST_VOICES=true; shift ;;
    -h|--help) usage 0 ;;
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

if ! [[ "$SPEED" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
  echo "Error: --speed must be a number from 0.25 to 4.0, got: $SPEED" >&2
  exit 2
fi

# Auto-detect provider
if [[ -z "$PROVIDER" ]]; then
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    PROVIDER="openai"
  else
    PROVIDER="macos"
  fi
fi

case "$PROVIDER" in
  openai|macos) ;;
  *) echo "Unknown provider: $PROVIDER (use openai or macos)" >&2; exit 2 ;;
esac

# Set default voice per provider
if [[ -z "$VOICE" ]]; then
  case "$PROVIDER" in
    openai) VOICE="coral" ;;
    macos) VOICE="Samantha" ;;
  esac
fi

# The names of the installed macOS voices, one per line. `say -v '?'` prints
# "<name> <locale> # <sample>", and a name can hold spaces and parentheses.
macos_voice_names() {
  say -v '?' | sed -E 's/[[:space:]]+[a-z]{2,3}[_-][A-Za-z0-9_]+[[:space:]]+#.*$//'
}

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
  usage 2 >&2
fi

if [[ ! -f "$SCRIPT_FILE" ]]; then
  echo "Error: script file not found: $SCRIPT_FILE" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Error: node is required (https://nodejs.org)." >&2
  exit 1
fi

# The JavaScript below is fixed text. Every value reaches it through an
# environment variable, never by pasting it into the code, so a quote in
# --instructions or in a path cannot break or change the program. It runs with
# `node --input-type=module -e`, so `import "openai"` resolves from the
# current directory, where the package was installed. No temp .mjs file.
#
# COMMON_JS reads and checks the scene list before any audio is made.
read -r -d '' COMMON_JS <<'JS' || true
import { readFileSync } from "node:fs";
import { join } from "node:path";

const env = process.env;
function fail(msg) {
  console.error("Error: " + msg);
  process.exit(1);
}
let scenes;
try {
  scenes = JSON.parse(readFileSync(env.TTS_SCRIPT_FILE, "utf8"));
} catch (e) {
  fail("cannot read the script file " + env.TTS_SCRIPT_FILE + ": " + e.message);
}
if (!Array.isArray(scenes) || scenes.length === 0) {
  fail("the script file must hold a non-empty JSON array of scenes");
}
const jobs = scenes.map((s, i) => {
  const n = i + 1;
  if (!s || typeof s !== "object" || Array.isArray(s)) fail("scene " + n + " is not an object");
  if (typeof s.text !== "string" || !s.text.trim()) fail("scene " + n + " has no \"text\"");
  const name = String(s.scene == null ? "scene" : s.scene).replace(/[^A-Za-z0-9_-]/g, "-") || "scene";
  const padded = String(n).padStart(2, "0");
  return { scene: s, label: padded + "-" + name, out: join(env.TTS_OUTPUT_DIR, padded + "-" + name + ".mp3") };
});
JS

read -r -d '' OPENAI_JS <<'JS' || true
import { writeFileSync } from "node:fs";
import OpenAI from "openai";

const openai = new OpenAI();
let done = 0;
for (const job of jobs) {
  console.log("Generating " + job.label + "...");
  try {
    const response = await openai.audio.speech.create({
      model: env.TTS_MODEL,
      voice: env.TTS_VOICE,
      input: job.scene.text,
      instructions: job.scene.instructions || env.TTS_INSTRUCTIONS,
      response_format: "mp3",
      speed: Number(env.TTS_SPEED),
    });
    const buffer = Buffer.from(await response.arrayBuffer());
    writeFileSync(job.out, buffer);
    done += 1;
    console.log("✓ " + job.out + " (" + Math.round(buffer.length / 1024) + " KB)");
  } catch (e) {
    fail(job.label + " failed after " + done + " of " + jobs.length + " files: " + (e && e.message ? e.message : e));
  }
}
console.log("\nGenerated " + done + " audio files.");
JS

read -r -d '' MACOS_JS <<'JS' || true
import { writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

let done = 0;
for (const job of jobs) {
  console.log("Generating " + job.label + "...");
  // The text goes to `say` in a file, so text that starts with "-" is not read as an option.
  const txt = join(env.TTS_TMP, job.label + ".txt");
  const aiff = join(env.TTS_TMP, job.label + ".aiff");
  writeFileSync(txt, job.scene.text);
  try {
    execFileSync("say", ["-v", env.TTS_VOICE, "-o", aiff, "-f", txt], { stdio: ["ignore", "inherit", "inherit"] });
    execFileSync("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", "-i", aiff,
      "-codec:a", "libmp3lame", "-qscale:a", "2", job.out], { stdio: ["ignore", "inherit", "inherit"] });
  } catch (e) {
    fail(job.label + " failed after " + done + " of " + jobs.length + " files: " + e.message);
  }
  done += 1;
  console.log("✓ " + job.out);
}
console.log("\nGenerated " + done + " audio files with macOS voice: " + env.TTS_VOICE);
JS

case "$PROVIDER" in
  openai)
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
      echo "Error: OPENAI_API_KEY not set." >&2
      echo "Set it with: export OPENAI_API_KEY=sk-..." >&2
      echo "Or use --provider macos for local TTS." >&2
      exit 1
    fi

    # Load the openai package from the current directory; install it there if missing.
    if ! node -e 'require.resolve("openai")' >/dev/null 2>&1; then
      echo "Installing the openai package in $PWD ..."
      if ! NPM_OUT=$(npm install --no-save openai 2>&1); then
        printf '%s\n' "$NPM_OUT" | tail -n 5 >&2
        echo "Error: npm install openai failed in $PWD" >&2
        exit 1
      fi
      if ! node -e 'require.resolve("openai")' >/dev/null 2>&1; then
        echo "Error: the openai package still cannot be loaded from $PWD after npm install" >&2
        exit 1
      fi
    fi

    mkdir -p "$OUTPUT_DIR"
    TTS_SCRIPT_FILE="$SCRIPT_FILE" TTS_OUTPUT_DIR="$OUTPUT_DIR" TTS_MODEL="$MODEL" \
      TTS_VOICE="$VOICE" TTS_INSTRUCTIONS="$INSTRUCTIONS" TTS_SPEED="$SPEED" \
      node --input-type=module -e "$COMMON_JS
$OPENAI_JS"
    ;;

  macos)
    if ! command -v say >/dev/null 2>&1; then
      echo "Error: the macos provider needs the say command, which only macOS has." >&2
      exit 1
    fi
    if ! command -v ffmpeg >/dev/null 2>&1; then
      echo "Error: ffmpeg required for macOS TTS. Install with: brew install ffmpeg" >&2
      exit 1
    fi
    if ! macos_voice_names | grep -Fxq -- "$VOICE"; then
      echo "Error: unknown macOS voice: $VOICE" >&2
      echo "List the installed voices with: $(basename "$0") --list-voices --provider macos" >&2
      exit 2
    fi

    mkdir -p "$OUTPUT_DIR"
    TTS_TMP="$(mktemp -d "${TMPDIR:-/tmp}/tts-macos.XXXXXX")"
    trap 'rm -rf "$TTS_TMP"' EXIT
    TTS_SCRIPT_FILE="$SCRIPT_FILE" TTS_OUTPUT_DIR="$OUTPUT_DIR" TTS_VOICE="$VOICE" TTS_TMP="$TTS_TMP" \
      node --input-type=module -e "$COMMON_JS
$MACOS_JS"
    ;;
esac
