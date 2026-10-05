#!/usr/bin/env bash
set -eu

usage() {
  cat <<EOF
Usage: $(basename "$0") <workflow> | --list | --help

Emit task manifest (JSON array) for product-video-creation workflows.

Workflows:
  full-video      Full narrated product video (9 tasks)
  visual-only     Video without voiceover (7 tasks)
  screenshots     Screenshot capture only (3 tasks)
  brand-update    Apply brand guidelines to existing video (3 tasks)
  voiceover-only  Add voiceover to existing video (3 tasks)

Options:
  --list          List available workflow names
  -h, --help      Show this help
EOF
  exit 0
}

case "${1:-}" in
  --list)
    echo "full-video"
    echo "visual-only"
    echo "screenshots"
    echo "brand-update"
    echo "voiceover-only"
    ;;
  full-video)
    cat <<'JSON'
[
  {"subject":"Voice selection brainstorm","activeForm":"Brainstorming voice options with user","description":"Present OpenAI TTS voices (13 options) vs macOS native voices. Wait for user selection."},
  {"subject":"Craft narrative (Opus agent)","activeForm":"Storyteller agent crafting narrative arc","description":"Launch product-video-storyteller (Opus) to create emotional arc, scene scripts, and voiceover narration. Present to user for approval."},
  {"subject":"Setup Remotion project","activeForm":"Setting up Remotion project with Tailwind","description":"Initialize or verify Remotion project, install dependencies including lucide-react"},
  {"subject":"Capture app screenshots","activeForm":"Capturing mobile screenshots with Playwright","description":"Take hero, flow steps, and results page screenshots at mobile viewport. Full-page for scroll effects."},
  {"subject":"Generate voiceover audio","activeForm":"Generating TTS audio per scene","description":"Run generate-voiceover.sh with selected provider/voice. Save per-scene MP3 files to public/audio/."},
  {"subject":"Create scene components","activeForm":"Building animated scene components","description":"Create 7 scenes using storyteller's narrative — not templates. Include AnimatedPhone, ScrollingPhone."},
  {"subject":"Apply brand guidelines","activeForm":"Applying brand colors, fonts, and tone","description":"Extract from brand PDF, map to video palette and typography, apply across all scenes."},
  {"subject":"Find background music","activeForm":"Music curator searching royalty-free tracks","description":"Launch product-video-music-curator to find tracks matching narrative arc and brand tone. Present options to user."},
  {"subject":"Mix audio and wire composition","activeForm":"Mixing voiceover with background music","description":"Add background music Audio component, set volume ducking, wire Sequence timing from audio durations."},
  {"subject":"Lint and preview","activeForm":"Running lint checks and launching preview","description":"Run eslint + tsc, start Remotion studio for preview"}
]
JSON
    ;;
  visual-only)
    cat <<'JSON'
[
  {"subject":"Craft narrative (Opus agent)","activeForm":"Storyteller agent crafting narrative arc","description":"Launch product-video-storyteller (Opus) to create emotional arc and scene scripts (no voiceover)."},
  {"subject":"Setup Remotion project","activeForm":"Setting up Remotion project with Tailwind","description":"Initialize or verify Remotion project, install dependencies"},
  {"subject":"Capture app screenshots","activeForm":"Capturing mobile screenshots with Playwright","description":"Take hero, flow, and results page screenshots at mobile viewport"},
  {"subject":"Create scene components","activeForm":"Building animated scene components","description":"Create 7 scenes using storyteller's narrative output"},
  {"subject":"Apply brand guidelines","activeForm":"Applying brand colors, fonts, and tone","description":"Extract and apply brand palette, typography, and visual style"},
  {"subject":"Wire composition","activeForm":"Composing scenes with timing and transitions","description":"Set up Sequence timing, crossfades, and total duration"},
  {"subject":"Lint and preview","activeForm":"Running lint checks and launching preview","description":"Run eslint + tsc, start Remotion studio for preview"}
]
JSON
    ;;
  screenshots)
    cat <<'JSON'
[
  {"subject":"Install Playwright","activeForm":"Installing Playwright and Chromium","description":"Ensure playwright package and chromium browser are available"},
  {"subject":"Capture app flow","activeForm":"Capturing app flow screenshots","description":"Navigate through app screens capturing each step at mobile viewport"},
  {"subject":"Capture results page","activeForm":"Capturing results/recommendation page","description":"Take full-page screenshot of results for scrolling animation"}
]
JSON
    ;;
  brand-update)
    cat <<'JSON'
[
  {"subject":"Extract brand guidelines","activeForm":"Reading brand guidelines document","description":"Parse PDF/document for colors, fonts, tone of voice"},
  {"subject":"Update scene styles","activeForm":"Applying brand styles to all scenes","description":"Replace colors, font families, and weights across all scene components"},
  {"subject":"Verify and preview","activeForm":"Running lint and previewing changes","description":"Ensure no build errors and preview updated video"}
]
JSON
    ;;
  voiceover-only)
    cat <<'JSON'
[
  {"subject":"Voice selection brainstorm","activeForm":"Brainstorming voice options with user","description":"Present OpenAI TTS vs macOS voice options. Wait for user selection."},
  {"subject":"Generate voiceover audio","activeForm":"Generating TTS audio per scene","description":"Run generate-voiceover.sh with selected provider/voice"},
  {"subject":"Sync audio to composition","activeForm":"Adding Audio components to Remotion","description":"Add <Audio> components, adjust scene durations to match audio lengths"}
]
JSON
    ;;
  -h|--help|"") usage ;;
  *) echo "Unknown workflow: $1" >&2; exit 2 ;;
esac
