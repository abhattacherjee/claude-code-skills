#!/usr/bin/env bash
set -eu

# Context Shield — Workflow Visualizer
# ASCII animations showing agents being dispatched and returning.
# Called by the skill at workflow milestones.

SCRIPT_NAME="$(basename "$0")"
SPEED="${SPEED:-fast}"  # fast (default), slow, instant

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME <scene> [options]

Scenes:
  manifest    --task "desc" --count N           Show manifest creation
  dispatch    --batch N --labels "a,b,c,d"      Agents leave the room
  working     --labels "a,b,c,d"                Agents working (brief)
  return      --batch N --labels "a,b,c,d"      Agents return with summaries
  synthesize  --done N --total N                Final synthesis
  complete    --task "desc"                     All done
  ralph-iter  --iteration N --remaining N       Ralph loop boundary
  full-demo                                     Run all scenes (demo mode)

Options:
  --speed fast|slow|instant   Animation speed (default: fast)
  -h, --help                  Show this help

Environment:
  SPEED=fast|slow|instant     Alternative to --speed flag
  NO_COLOR=1                  Disable colors

Examples:
  $SCRIPT_NAME manifest --task "Analyze 8 Figma frames" --count 8
  $SCRIPT_NAME dispatch --batch 1 --labels "Homepage,Search,Results,Detail"
  $SCRIPT_NAME return --batch 1 --labels "Homepage,Search,Results,Detail"
  $SCRIPT_NAME synthesize --done 8 --total 8
  $SCRIPT_NAME full-demo
EOF
  exit 0
}

# --- Color & timing ---

# Colors: always enable unless NO_COLOR is set.
# Claude Code's UI renders ANSI colors even though stdout isn't a terminal.
if [[ -n "${NO_COLOR:-}" ]]; then
  RST="" BLD="" DIM=""
  RED="" GRN="" YLW="" BLU="" MAG="" CYN="" WHT=""
else
  RST="\033[0m"  BLD="\033[1m"  DIM="\033[2m"
  RED="\033[31m" GRN="\033[32m" YLW="\033[33m"
  BLU="\033[34m" MAG="\033[35m" CYN="\033[36m" WHT="\033[37m"
fi

# When stdout is not a terminal (e.g., Claude Code's captured output),
# force instant mode — sleep/animation has no visual effect.
if [[ ! -t 1 ]]; then
  SPEED="instant"
fi

pause() {
  case "$SPEED" in
    instant) ;;
    fast)  sleep "${1:-0.15}" ;;
    slow)  sleep "$(echo "${1:-0.15} * 3" | bc)" ;;
  esac
}

type_text() {
  # In captured output, just print the text — no character-by-character effect.
  echo -e "$1"
}

# --- Character sprites ---

ORCHESTRATOR_IDLE="
${BLD}${CYN}    ╭─────╮
    │ ◉ ◉ │
    │  ▽  │
    ╰──┬──╯
       │
    ╭──┴──╮
    │ORCH.│
    ╰─────╯${RST}"

ORCHESTRATOR_DISPATCH="
${BLD}${CYN}    ╭─────╮
    │ ◉ ◉ │
    │  ◇  │
    ╰──┬──╯
      ╱│╲
    ╭──┴──╮
    │ORCH.│
    ╰─────╯${RST}"

ORCHESTRATOR_RECEIVE="
${BLD}${CYN}    ╭─────╮
    │ ◕ ◕ │
    │  ▿  │
    ╰──┬──╯
     ╲ │╱
    ╭──┴──╮
    │ORCH.│
    ╰─────╯${RST}"

agent_sprite() {
  local label="$1" color="$2" state="$3"
  local face="◉ ◉" mouth="─"
  case "$state" in
    idle)    face="◉ ◉"; mouth="─" ;;
    walking) face="◉ ◉"; mouth="○" ;;
    reading) face="◉ ◉"; mouth="□" ;;  # reading/fetching
    done)    face="◕ ◕"; mouth="▿" ;;  # happy, job done
    failed)  face="◉ ◉"; mouth="╳" ;;
  esac
  echo -e "${color} ╭───╮${RST}"
  echo -e "${color} │${face}│${RST}"
  echo -e "${color} │ ${mouth} │${RST}"
  echo -e "${color} ╰─┬─╯${RST}"
  echo -e "${color}   │${RST}"
  printf " ${DIM}%-5.5s${RST}\n" "$label"
}

# --- Scenes ---

scene_manifest() {
  local task="$1" count="$2"
  echo ""
  echo -e "${BLD}${YLW}  ━━━ CONTEXT SHIELD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
  echo ""
  type_text "  ${DIM}Creating manifest...${RST}" 0.03
  pause 0.3
  echo ""
  echo -e "  ${BLD}📋 Task:${RST} $task"
  echo -e "  ${BLD}📦 Sources:${RST} $count items"
  echo ""
  # Manifest visualization
  echo -e "  ${DIM}┌──────────────────────────────────────────┐${RST}"
  echo -e "  ${DIM}│${RST}  ${BLD}manifest.json${RST}                          ${DIM}│${RST}"
  echo -e "  ${DIM}│${RST}                                          ${DIM}│${RST}"
  local i
  for (( i=1; i<=count && i<=6; i++ )); do
    echo -e "  ${DIM}│${RST}   ${YLW}○${RST} Source $i ........................ ${DIM}pending${RST} ${DIM}│${RST}"
    pause 0.1
  done
  if [[ $count -gt 6 ]]; then
    echo -e "  ${DIM}│${RST}   ${DIM}... and $((count - 6)) more${RST}                      ${DIM}│${RST}"
  fi
  echo -e "  ${DIM}└──────────────────────────────────────────┘${RST}"
  echo ""
}

scene_dispatch() {
  local batch="$1"
  shift
  local labels=("$@")
  local n=${#labels[@]}
  local colors=("$MAG" "$BLU" "$GRN" "$YLW")

  echo ""
  echo -e "  ${BLD}${CYN}━━━ BATCH $batch: DISPATCHING $n AGENTS ━━━${RST}"
  echo ""

  # Orchestrator sends agents out
  echo -e "$ORCHESTRATOR_DISPATCH"
  pause 0.3

  echo ""
  type_text "  ${DIM}Spawning parallel agents...${RST}" 0.02
  echo ""

  # Agents walking out the door
  local door="  ┌─── CONTEXT BOUNDARY ───┐"
  echo -e "${DIM}$door${RST}"
  pause 0.2

  for (( i=0; i<n; i++ )); do
    local label="${labels[$i]}"
    local color="${colors[$((i % 4))]}"
    pause 0.2

    # Agent walks through the door
    echo -e "  ${DIM}│${RST}                          ${DIM}│${RST}"
    echo -e "  ${DIM}│${RST}  ${color}╭───╮${RST}                  ${DIM}│${RST}"
    echo -e "  ${DIM}│${RST}  ${color}│◉ ◉│${RST}  ${DIM}───────────▶${RST}  ${DIM}│${RST}  ${BLD}${label}${RST}"
    echo -e "  ${DIM}│${RST}  ${color}│ ○ │${RST}                  ${DIM}│${RST}  ${DIM}(isolated context)${RST}"
    echo -e "  ${DIM}│${RST}  ${color}╰─┬─╯${RST}                  ${DIM}│${RST}"
  done

  echo -e "  ${DIM}│${RST}                          ${DIM}│${RST}"
  echo -e "  ${DIM}└──────────────────────────┘${RST}"
  echo ""
  echo -e "  ${DIM}Each agent reads heavy content in its own context.${RST}"
  echo -e "  ${DIM}Parent context stays clean.${RST}"
  echo ""
}

scene_working() {
  local labels=("$@")
  local n=${#labels[@]}
  local colors=("$MAG" "$BLU" "$GRN" "$YLW")
  # Tools each agent might use — one per agent for a snapshot feel
  local tools=("WebFetch" "Read" "Analyzing" "Distilling" "Grep" "get_design")

  echo ""
  echo -e "  ${BLD}Agents working in isolation:${RST}"
  echo ""
  echo -e "  ${DIM}┌──────────────────────────────────────────┐${RST}"

  for (( i=0; i<n; i++ )); do
    local label="${labels[$i]}"
    local color="${colors[$((i % 4))]}"
    local tool="${tools[$((i % ${#tools[@]}))]}"
    printf "  ${DIM}│${RST}  ${color}◉${RST} ${BLD}%-12.12s${RST} ${DIM}━━━${RST} ${CYN}%-11.11s${RST}${DIM}...${RST} ${DIM}│${RST}\n" "$label" "$tool"
  done

  echo -e "  ${DIM}│${RST}                                          ${DIM}│${RST}"
  echo -e "  ${DIM}│${RST}  ${DIM}Each agent absorbs ~50K tokens${RST}           ${DIM}│${RST}"
  echo -e "  ${DIM}│${RST}  ${DIM}Returns only ~500 token summary${RST}          ${DIM}│${RST}"
  echo -e "  ${DIM}└──────────────────────────────────────────┘${RST}"
  echo ""
}

scene_return() {
  local batch="$1"
  shift
  local labels=("$@")
  local n=${#labels[@]}
  local colors=("$MAG" "$BLU" "$GRN" "$YLW")

  echo ""
  echo -e "  ${BLD}${GRN}━━━ BATCH $batch: AGENTS RETURNING ━━━${RST}"
  echo ""

  local door="  ┌─── CONTEXT BOUNDARY ───┐"
  echo -e "${DIM}$door${RST}"

  for (( i=0; i<n; i++ )); do
    local label="${labels[$i]}"
    local color="${colors[$((i % 4))]}"
    pause 0.25

    echo -e "  ${DIM}│${RST}                          ${DIM}│${RST}"
    echo -e "  ${DIM}│${RST}  ${color}╭───╮${RST}                  ${DIM}│${RST}"
    echo -e "  ${DIM}│${RST}  ${color}│◕ ◕│${RST}  ${GRN}◀───────────${RST}  ${DIM}│${RST}  ${BLD}${label}${RST}"
    echo -e "  ${DIM}│${RST}  ${color}│ ▿ │${RST}  ${GRN}~500 tokens${RST}   ${DIM}│${RST}  ${GRN}✓ distilled${RST}"
    echo -e "  ${DIM}│${RST}  ${color}╰─┬─╯${RST}                  ${DIM}│${RST}"
  done

  echo -e "  ${DIM}│${RST}                          ${DIM}│${RST}"
  echo -e "  ${DIM}└──────────────────────────┘${RST}"
  echo ""

  # Orchestrator receives
  echo -e "$ORCHESTRATOR_RECEIVE"
  pause 0.2
  echo ""
  echo -e "  ${GRN}✓${RST} Batch $batch complete — $n summaries collected"
  echo -e "  ${DIM}Raw content: ~${n}x50K tokens → Summaries: ~${n}x500 tokens${RST}"
  echo ""
}

scene_synthesize() {
  local done="$1" total="$2"

  echo ""
  echo -e "  ${BLD}${CYN}━━━ SYNTHESIS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
  echo ""
  echo -e "$ORCHESTRATOR_RECEIVE"
  echo ""

  echo -e "  ${DIM}Combining $done distilled summaries...${RST}"
  echo ""

  echo -e "  ${DIM}┌──────────────────────────────────────────┐${RST}"
  echo -e "  ${DIM}│${RST}  ${BLD}Distilled Knowledge${RST}                     ${DIM}│${RST}"
  echo -e "  ${DIM}│${RST}                                          ${DIM}│${RST}"

  local i
  for (( i=1; i<=done && i<=8; i++ )); do
    pause 0.1
    echo -e "  ${DIM}│${RST}   ${GRN}●${RST} Summary $i ..................... ${GRN}~500t${RST} ${DIM}│${RST}"
  done
  if [[ $done -gt 8 ]]; then
    echo -e "  ${DIM}│${RST}   ${DIM}... and $((done - 8)) more${RST}                      ${DIM}│${RST}"
  fi

  echo -e "  ${DIM}│${RST}                                          ${DIM}│${RST}"
  echo -e "  ${DIM}│${RST}  ${BLD}Total: ~$((done * 500)) tokens${RST}  ${DIM}(was ~$((done * 50))K)${RST}  ${DIM}│${RST}"
  echo -e "  ${DIM}└──────────────────────────────────────────┘${RST}"
  echo ""
}

scene_complete() {
  local task="$1"

  echo ""
  echo -e "  ${BLD}${GRN}━━━ CONTEXT SHIELD COMPLETE ━━━━━━━━━━━━━━━━━━━━${RST}"
  echo ""
  echo -e "  ${GRN}╭───────────────────────────────────────────────╮${RST}"
  echo -e "  ${GRN}│${RST}                                               ${GRN}│${RST}"
  echo -e "  ${GRN}│${RST}   ${BLD}✓ All sources distilled${RST}                     ${GRN}│${RST}"
  echo -e "  ${GRN}│${RST}   ${BLD}✓ Parent context preserved${RST}                  ${GRN}│${RST}"
  echo -e "  ${GRN}│${RST}   ${BLD}✓ Summaries ready for synthesis${RST}             ${GRN}│${RST}"
  echo -e "  ${GRN}│${RST}                                               ${GRN}│${RST}"
  echo -e "  ${GRN}│${RST}   ${DIM}Task: $task${RST}"
  echo -e "  ${GRN}│${RST}                                               ${GRN}│${RST}"
  echo -e "  ${GRN}╰───────────────────────────────────────────────╯${RST}"
  echo ""
}

scene_ralph_iter() {
  local iteration="$1" remaining="$2"

  echo ""
  echo -e "  ${BLD}${MAG}━━━ RALPH LOOP: ITERATION BOUNDARY ━━━━━━━━━━━━${RST}"
  echo ""
  echo -e "  ${MAG}╭─────────────────────────────────────────────╮${RST}"
  echo -e "  ${MAG}│${RST}                                             ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}  ${BLD}🔄 Iteration $iteration complete${RST}                    ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}                                             ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}  ${DIM}Context: wiped clean (fresh start)${RST}        ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}  ${DIM}Manifest: $remaining items remaining on disk${RST}      ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}  ${DIM}Next: stop hook feeds prompt back${RST}          ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}                                             ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}     ${DIM}┌─ context ──┐   ┌─ context ──┐${RST}      ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}     ${DIM}│ iteration $iteration │ → │ iteration $((iteration+1)) │${RST}      ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}     ${DIM}│  (done)    │   │  (fresh)   │${RST}      ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}     ${DIM}└────────────┘   └────────────┘${RST}      ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}            ${DIM}↓ manifest.json ↓${RST}              ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}         ${DIM}(state persists on disk)${RST}           ${MAG}│${RST}"
  echo -e "  ${MAG}│${RST}                                             ${MAG}│${RST}"
  echo -e "  ${MAG}╰─────────────────────────────────────────────╯${RST}"
  echo ""
}

scene_full_demo() {
  echo ""
  echo -e "${BLD}${CYN}  ╔═══════════════════════════════════════════════╗${RST}"
  echo -e "${BLD}${CYN}  ║         CONTEXT SHIELD — DEMO MODE           ║${RST}"
  echo -e "${BLD}${CYN}  ╚═══════════════════════════════════════════════╝${RST}"
  echo ""

  scene_manifest "Analyze 8 Figma design frames" 8
  pause 0.5

  local batch1=("Homepage" "Search" "Results" "Detail")
  scene_dispatch 1 "${batch1[@]}"
  scene_working "${batch1[@]}"
  scene_return 1 "${batch1[@]}"
  pause 0.3

  scene_ralph_iter 1 4
  pause 0.5

  local batch2=("Checkout" "Profile" "Settings" "Mobile")
  scene_dispatch 2 "${batch2[@]}"
  scene_working "${batch2[@]}"
  scene_return 2 "${batch2[@]}"
  pause 0.3

  scene_synthesize 8 8
  pause 0.3

  scene_complete "Analyze 8 Figma design frames"
}

# --- Main ---

[[ $# -eq 0 ]] && usage

COMMAND=""
TASK="" COUNT="" BATCH="" LABELS="" DONE="" TOTAL="" ITERATION="" REMAINING=""

# Parse global options first
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --speed)   SPEED="$2"; shift 2 ;;
    *)         args+=("$1"); shift ;;
  esac
done
# An empty array is "unbound" under set -u on bash 3.2 (the macOS default).
set -- ${args[@]+"${args[@]}"}

COMMAND="${1:-}"
if [[ $# -gt 0 ]]; then shift; fi

# Parse command-specific options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)      TASK="$2"; shift 2 ;;
    --count)     COUNT="$2"; shift 2 ;;
    --batch)     BATCH="$2"; shift 2 ;;
    --labels)    LABELS="$2"; shift 2 ;;
    --done)      DONE="$2"; shift 2 ;;
    --total)     TOTAL="$2"; shift 2 ;;
    --iteration) ITERATION="$2"; shift 2 ;;
    --remaining) REMAINING="$2"; shift 2 ;;
    *)           shift ;;
  esac
done

# Split labels into array
LABEL_ARR=()
if [[ -n "${LABELS:-}" ]]; then
  IFS=',' read -ra LABEL_ARR <<< "$LABELS"
fi

case "$COMMAND" in
  manifest)    scene_manifest "${TASK:-Task}" "${COUNT:-4}" ;;
  dispatch)    scene_dispatch "${BATCH:-1}" ${LABEL_ARR[@]+"${LABEL_ARR[@]}"} ;;
  working)     scene_working ${LABEL_ARR[@]+"${LABEL_ARR[@]}"} ;;
  return)      scene_return "${BATCH:-1}" ${LABEL_ARR[@]+"${LABEL_ARR[@]}"} ;;
  synthesize)  scene_synthesize "${DONE:-4}" "${TOTAL:-4}" ;;
  complete)    scene_complete "${TASK:-Task}" ;;
  ralph-iter)  scene_ralph_iter "${ITERATION:-1}" "${REMAINING:-0}" ;;
  full-demo)   scene_full_demo ;;
  *)           echo "Unknown scene: $COMMAND" >&2; exit 1 ;;
esac
