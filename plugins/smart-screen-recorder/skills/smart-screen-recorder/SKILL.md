---
name: smart-screen-recorder
description: "AI-driven screen recording and demo production pipeline for macOS. Records screen + cursor + window bounds, then uses AI vision to analyze the recording, create a zoom script targeting specific UI elements, generate voiceover narration, and produce a polished demo video. Use when: (1) creating product demo videos, (2) recording and polishing UI walkthroughs, (3) turning raw screen recordings into narrated presentations, (4) re-processing existing recordings with different zoom/voiceover."
metadata:
  version: 4.3.0
---

# Smart Screen Recorder

AI-driven demo video production from raw screen recordings. Records your screen,
then uses Claude's vision to analyze the recording, identify narrative moments,
create a zoom script targeting actual UI elements, generate voiceover, and produce
a polished demo video. Works with any product or UI — the user provides a brief
description of what they're demoing and the AI crafts the narrative around it.

## Quick Check

```bash
# Install dependencies
~/.claude/skills/smart-screen-recorder/scripts/install-deps.sh

# Record (Ctrl+C to stop) — captures screen + cursor + window bounds
~/.claude/skills/smart-screen-recorder/scripts/record.sh

# Then tell Claude: "process my recording into a demo video"
```

## Pipeline Overview

```
Record ──→ Extract ──→ Voice ──→ Demo Director ──→ TTS ──→ Integrated ──→ Post-Prod
  │          Frames     Select     (AI agent)       │       Timeline       Review
  MKV +      as PNGs    (user)     Writes zoom +    OpenAI  Renderer       (AI agent)
  cursor     + manifest            voiceover +      TTS     Interleaves    PASS or
  .jsonl                           hold_frames      nova    PLAY + HOLD    NEEDS_FIXES
```

**Key architecture (v4.0): Narration-first integrated timeline.**

The video and narration are built TOGETHER, not separately:
1. Each narration segment is paired with a specific source frame to freeze on
2. The renderer alternates between PLAY (advance source) and HOLD (freeze + narrate)
3. The output video is LONGER than the source recording — the extra time is frozen
   frames where the narrator describes what's on screen
4. Audio is placed at exact output timestamps where each hold begins

This replaces the old approach where voiceover was overlaid on a continuously-playing
video that rushed past the content being described.

## Progress Tracking (MANDATORY)

**Before starting, create a task checklist so the user always knows where we are.**

Use `TaskCreate` at the start to create these tasks. Mark each `in_progress` when starting,
`completed` when done. The user sees this as a live progress indicator.

| # | Task | Description |
|---|------|-------------|
| 1 | Record screen | Capture raw video + cursor data |
| 2 | Extract frames | Pull key frames as PNGs for AI analysis |
| 3 | Voice & context | Select TTS voice + gather product description |
| 4 | Brainstorm narrative | Present demo theme options, get user direction |
| 5 | Demo Director | AI analyzes frames, creates zoom + voiceover scripts |
| 6 | Verify zoom targets | QA verifier corrects bounding boxes at full resolution |
| 7 | Generate TTS | Create audio segments from voiceover script |
| 8 | Build timeline | Construct integrated PLAY + HOLD segment sequence |
| 9 | Preview & feedback | Serve HTML preview, iterate on user feedback |
| 10 | Render video | Full 4K render from approved timeline |
| 11 | Mix audio | Place TTS segments at precise output timestamps |
| 12 | Post-production | Quality gate: PASS / NEEDS_FIXES / RESHOOT |

**Update rules:**
- Mark `in_progress` immediately before starting each task
- Mark `completed` immediately after it succeeds
- If a task requires user input (3, 4, 9), mark `in_progress` while waiting
- If preview feedback requires re-work, mark affected tasks back to `in_progress`
- On abort, mark remaining tasks as `deleted`

**Skip tasks that don't apply** (e.g., skip Step 1 if user provides existing recording).

## Step-by-Step Workflow

### Step 1: Record

```bash
~/.claude/skills/smart-screen-recorder/scripts/record.sh --raw-only -o ~/Desktop
```

Output: `{name}-raw.mp4` + `{name}-cursor.jsonl`. Uses MKV internally (survives
Ctrl+C interruption), then remuxes to MP4.

### Step 2: Extract Key Frames

```bash
python3 ~/.claude/skills/smart-screen-recorder/scripts/extract-frames.py \
  recording-raw.mp4 cursor.jsonl -o ~/Desktop/zoom-analysis
```

### Step 3: Voice Selection (Interactive)

**Before generating anything, ask the user their voice preference.** Present these options:

```
What voice style would you like for the narration?

1. OpenAI TTS (natural, human-like) — requires OpenAI API key
   a) nova    — warm, engaging female (recommended for product demos)
   b) alloy   — neutral, versatile
   c) echo    — deeper male voice
   d) shimmer — soft, gentle female
   e) onyx    — authoritative male
   f) fable   — expressive, storytelling

2. macOS Native (free, more synthetic)
   a) Samantha — standard US female
   b) Reed     — US male
   c) Flo      — casual female

Your choice:
```

**If OpenAI selected:**
- Check if `OPENAI_API_KEY` is set in the environment
- If not: guide user to get one — "Set your API key: `export OPENAI_API_KEY=sk-...`"
  Or if user prefers browser auth, open `https://platform.openai.com/api-keys`
- Verify the key works: test with a short TTS call before full generation

**Save the preference** in the voiceover-script.json so re-processing uses the same voice.

### Step 3.5: Gather User Context (CRITICAL)

**Before launching the Demo Director, ask the user:**

```
What product/feature is this demo showing? Give me a brief description:
- What does the product do?
- Who is the target audience?
- What's the key narrative? (e.g., "show how easy it is to create a project")
```

This context is passed to the Demo Director so it can craft narration that accurately
describes the product, rather than guessing from screenshots alone. The user's description
becomes the `product_context` field in the Demo Director prompt.

### Step 3.7: Narrative Brainstorming (Agent + Interactive)

**Before the Demo Director runs, launch the Demo Storyteller agent to craft theme options.**

This is a two-part step: the AI proposes, the user chooses.

**Part 1: Launch Demo Storyteller agent**

Launch a `general-purpose` sub-agent using the **Demo Storyteller** persona
(`~/.claude/agents/demo-storyteller.md`). Pass it:
- The extracted frames directory
- The manifest.json
- The product context from Step 3.5
- The chosen TTS voice

The agent reads ALL frames, identifies compelling moments, and writes
`narrative-themes.json` with 3 distinct narrative approaches. Each theme includes:
- Name, tagline, tone, target audience
- Concrete opening line (so the user can "hear" the difference)
- Narrative arc, pacing, and which sections to emphasize vs skip

**Part 2: Present to user and capture choice**

Present the 3 themes to the user using the Storyteller's formatted summary.
The user picks one theme, mixes elements, or provides their own direction.

Capture the result as `narrative_brief` — a structured object passed to the Demo Director:

```json
{
  "chosen_theme": "A",
  "theme_name": "The Journey",
  "tone": "warm, personal, storytelling",
  "opening_line": "Meet the Escape Planner...",
  "narrative_arc": "Follow a first-time user from curiosity to delight",
  "emphasis": ["questionnaire flow", "AI generation reveal", "tiny home match scores"],
  "de_emphasis": ["scrolling between sections", "loading states"],
  "user_notes": "Any additional direction from the user"
}
```

**Why an agent instead of hardcoded options:** The Storyteller reads the actual frames,
so its themes reference real UI elements and screens — not generic templates. A recording
of a code editor gets different themes than a recording of a vacation planner.

### Step 4: AI Analysis (Demo Director)

Launch a `general-purpose` sub-agent as a **Senior Product Demo Director** persona.
Pass the user's product description as context.
The agent must read ALL extracted frames and produce `zoom-script.json` + `voiceover-script.json`.

**zoom-script.json** format:
```json
{
  "trim": {"start": 27, "end": 125},
  "video_resolution": {"w": 6016, "h": 3384},
  "default_zoom": 1.0,
  "events": [
    {
      "description": "What UI element and why it matters narratively",
      "start": 44, "end": 51,
      "zoom": 1.5,
      "target_box": {"x": 1750, "y": 250, "w": 2000, "h": 1550},
      "target_element": "Interest selection grid with colorful tag pills",
      "transition_in": 2.5, "transition_out": 2.0
    }
  ]
}
```

**Demo Director rules:**
- Default is WIDE (zoom 1.0) — zoom only at narrative peaks
- Maximum 3-4 zoom events in the entire video
- Use **bounding boxes** (`target_box`) that encompass the ENTIRE UI element
- Include `target_element` description so the verification step knows what to look for
- Gentle zoom (1.4-1.7x), slow transitions (2-2.5s ease-in-out)
- Trim start/end to cut non-demo portions
- Voiceover: conversational, short sentences, contractions, dramatic pauses
- Voice field should match user's Step 3 selection

### Step 5: Verify & Correct Zoom Targets (CRITICAL)

**The Demo Director's bounding boxes are estimates from thumbnail-sized frames.
They are often wrong. This verification step is mandatory.**

Launch a second `general-purpose` sub-agent as a **Zoom QA Verifier**. For each
zoom event in the script:

1. Extract the ACTUAL video frame at that event's timestamp (at full resolution)
2. Read the frame image with Claude vision
3. Identify the `target_element` described in the zoom event
4. Determine the correct bounding box for that element in the full-resolution frame
5. Update `target_box` coordinates in the zoom script

The verifier should:
- Read the frame at `trim.start + event.start` seconds
- Look for the described UI element (e.g., "interest selection grid with colorful tag pills")
- Measure where that element actually is in the 6016x3384 frame
- Ensure the bounding box centers the element with comfortable padding (10-15% margin)
- Write the corrected zoom-script.json

**Why this step exists:** The Demo Director sees 1920px-wide thumbnails but the video
is 6016px wide. Even small estimation errors at thumbnail scale become 200-300px
misalignment at full resolution, causing the zoom to target the wrong area.

### Step 6: Build Integrated Timeline

**This is the core of v4.0.** Instead of overlaying audio on a continuously-playing
video, build an **integrated timeline** that interleaves PLAY and HOLD segments:

```python
timeline = [
    {"type": "play", "source_start": 0.0, "source_end": 5.0, "duration": 1.5},
    {"type": "hold_narrate", "source_time": 5.0, "hold_duration": 5.3,
     "narration": "Meet the app. Here's what it does...", "tts_file": "seg_00.mp3"},
    {"type": "play", "source_start": 6.0, "source_end": 10.0, "duration": 1.5},
    {"type": "hold_narrate", "source_time": 10.0, "hold_duration": 4.8,
     "narration": "It starts with a simple setup flow...", "tts_file": "seg_02.mp3"},
    ...
]
```

**How to build the timeline:**
1. Read the voiceover script — each narration segment has a `start_time` (source timeline)
2. For each segment: play source video UP TO that point (1-1.5s max), then HOLD on
   that frame for the narration duration + 0.3s buffer
3. Advance source by 1s after each hold (the user's screen moved slightly during the hold)
4. Compress play segments to 1.5s max — the viewer doesn't need to watch scrolling in real-time
5. Remove silence beats (the holds provide natural pacing)

**Target output duration:** Source duration + ~40% for holds. A 98s source → ~135s output.

### Step 7: Generate TTS and Render

Generate TTS segments (OpenAI or macOS), then render the integrated timeline:

1. **Generate TTS** for each narration segment
2. **Render video** — the integrated timeline renderer alternates between:
   - `play`: read source frames and write to encoder
   - `hold_narrate`: read ONE source frame, write it N times (freeze), record TTS placement
3. **Mix audio** — place each TTS segment at its exact output timestamp (where the hold begins)
4. **Merge** video + audio

The renderer tracks `tts_placement` — a list of `{file, output_time, duration}` entries
that tell ffmpeg where to place each audio segment in the final mix.

### Step 7.5: Preview Before Rendering (MANDATORY)

**Before spending 5+ minutes on a full render, generate an HTML preview.**

```bash
python3 ~/.claude/skills/smart-screen-recorder/scripts/preview-timeline.py \
  raw.mp4 zoom-script.json integrated-timeline.json tts/ -o preview/
```

This opens a localhost page (http://localhost:8111) showing:
- A screenshot for each HOLD frame (what the viewer will see)
- Play buttons for each TTS segment (what the viewer will hear)
- Timeline structure (PLAY durations, HOLD durations, output timestamps)
- A "Play All" button to hear the full narration sequentially

**The user reviews and provides feedback** (e.g., "Hold 3 narration mentions tiny homes
but the frame shows excursions — move to Hold 6"). Adjust the zoom-script.json and
voiceover-script.json based on feedback, then rebuild the timeline and re-preview.

**Only proceed to full render after the user approves the preview.**

### Step 8: Post-Production Review (Quality Gate)

**Launch the Post-Production Editor agent** (`demo-post-production-editor`) to review
the final output. The editor:

1. Samples frames from the OUTPUT video at each zoom event's midpoint
2. Verifies the zoomed UI element is centered and fully visible
3. Checks voiceover timing matches on-screen content
4. Evaluates narrative flow and pacing
5. Returns a verdict: PASS, NEEDS_FIXES, or RESHOOT

**If NEEDS_FIXES:** Apply the editor's recommended changes:
- `adjust_zoom` → update zoom-script.json bounding boxes, re-run Step 6
- `rewrite_voiceover` → update voiceover-script.json, regenerate TTS
- `shift_timing` → adjust zoom start/end times
- `add_pause` → insert silence beats in voiceover

**If RESHOOT:** The recording itself is inadequate. Inform the user and offer to
re-record with guidance on what to demo differently.

**If PASS:** The demo is ready to ship.

### Step 9: Manual Review and Iterate

Both scripts are editable JSON. To re-process without re-recording:
```bash
# Edit zoom-script.json or voiceover-script.json
python3 ~/.claude/skills/smart-screen-recorder/scripts/apply-zoom-script.py \
  raw.mp4 zoom-script.json -o output.mp4 --resolution 3840x2160
```

## Agent Definitions

| Agent | File | Model | Purpose |
|-------|------|-------|---------|
| Demo Storyteller | `~/.claude/agents/demo-storyteller.md` | sonnet | Analyzes frames, proposes 3 narrative themes for user to choose from |
| Demo Director | `~/.claude/agents/demo-director.md` | opus | Analyzes all frames + narrative brief, creates zoom-script.json + voiceover-script.json |
| Zoom QA Verifier | `~/.claude/agents/zoom-qa-verifier.md` | opus | Extracts full-res frames at zoom timestamps, corrects bounding boxes |
| Voiceover Timing Fixer | `~/.claude/agents/voiceover-timing-fixer.md` | sonnet | Detects TTS audio overlaps, rebuilds sequential timestamps |
| Post-Production Editor | `~/.claude/agents/demo-post-production-editor.md` | opus | Reviews final output for quality, requests re-cuts if needed |

All agents are NOT user-invocable — spawned by the skill orchestrator.

**Sub-Agent Registry:**

| Phase | Agent | Concurrency | Input | Output |
|-------|-------|-------------|-------|--------|
| Step 3.7 | Demo Storyteller | Sequential | Frames + product context | narrative-themes.json (3 options) |
| Step 4 | Demo Director | Sequential (after user picks theme) | Frames + narrative brief | zoom-script.json, voiceover-script.json |
| Step 5 | Zoom QA Verifier | Sequential (after Step 4) | zoom-script.json + raw video | Corrected zoom-script.json |
| Step 7b | Voiceover Timing Fixer | Sequential (after Step 7) | TTS audio files + manifest | Fixed manifest with 0 overlaps |
| Step 8 | Post-Production Editor | Sequential (after merge) | Final video + zoom/VO scripts | PASS/NEEDS_FIXES/RESHOOT verdict |

## Team Mode (Optional)

When Agent Teams are enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), the pipeline can use persistent teammates instead of one-shot sub-agents.

### Why Teams Help Here

The standard pipeline launches 5 sequential sub-agents — each starts fresh with no memory of prior phases. Teams change this:

1. **Persistent creative team**: Instead of destroying agents between phases, teammates persist across the session. The Director can refer back to the Storyteller's themes. The QA Verifier can ask the Director about intent behind a zoom target. The Post-Production Editor can request the Timing Fixer to adjust specific segments — all without re-explaining context.

2. **Parallel iteration**: During the preview-feedback cycle (Step 9), multiple teammates can work simultaneously — one regenerating TTS clips for segments the user flagged, while another adjusts zoom targets, and a third rewrites narration for a different section.

3. **Cross-phase communication**: When the Post-Production Editor returns NEEDS_FIXES, it can message the Director directly about which narration segments need rewriting, rather than the orchestrator relaying instructions.

### Team Structure

```
TeamCreate("demo-production")
├── storyteller   — brainstorms themes, stays available for creative reference
├── director      — creates zoom + voiceover scripts, iterates on feedback
├── qa-verifier   — validates zoom targets, can ask director about intent
└── Lead orchestrates phases, manages user feedback, coordinates iteration
```

The Voiceover Timing Fixer and Post-Production Editor roles are handled by the lead or existing teammates, since their work is tightly coupled with the Director's output.

### When to Use Teams vs Sub-Agents

| Scenario | Recommendation |
|----------|---------------|
| Single recording, no iteration | Sub-agents (simpler) |
| Multiple recordings in one session | Teams (reuse creative direction) |
| Heavy preview-feedback iteration | Teams (parallel fixes) |
| User wants to re-process with different narrative | Teams (Storyteller remembers previous themes) |

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `record.sh` | Record screen + cursor + window bounds (MKV → MP4) |
| `cursor-tracker.py` | Track cursor, clicks, active window via Quartz API |
| `extract-frames.py` | Extract key frames as PNGs for AI analysis |
| `apply-zoom-script.py` | Apply zoom script with trim, bounding boxes, 4K output |
| `generate-tts.py` | Generate OpenAI/macOS TTS audio from voiceover script |
| `build-timeline.py` | Build integrated PLAY+HOLD timeline from zoom + TTS |
| `render-timeline.py` | Render video from integrated timeline with zoom |
| `mix-audio.py` | Mix TTS audio segments into rendered video at timestamps |
| `smart-zoom.py` | Legacy heuristic zoom modes (focus/click/velocity) |
| `install-deps.sh` | Install ffmpeg, pyobjc, opencv, numpy |

## Dependencies

| Dependency | Install | Purpose |
|------------|---------|---------|
| ffmpeg | `brew install ffmpeg` | Screen capture + video encoding |
| pyobjc-framework-Quartz | `pip3 install pyobjc-framework-Quartz` | Cursor + window tracking |
| opencv-python | `pip3 install opencv-python` | Frame extraction + processing |
| numpy | (with opencv) | Array operations |
| OPENAI_API_KEY (optional) | `export OPENAI_API_KEY=sk-...` | Natural TTS voices |

macOS only. Requires Screen Recording permission for Terminal. Click tracking
requires Accessibility permission.

## Lessons Learned

1. **Heuristic zoom (velocity/dwell) fails for UI demos** — cursor speed doesn't
   correlate with what's worth zooming into. AI vision analysis is essential.
2. **Record to MKV, not MP4** — MP4 writes the moov atom at the end; interruption
   corrupts the file. MKV writes metadata incrementally and survives Ctrl+C.
3. **AVFoundation requires `-pixel_format nv12`** — the default `yuv420p` isn't
   supported as input. Capture in nv12, encode to yuv420p on output.
4. **4K output preserves text legibility** — 1920x1080 from a Retina source
   destroys text. Output at 3840x2160 minimum.
5. **No window cropping** — hardcoded crop coordinates cut off UI elements.
   Keep the full frame; let zoom handle focus.
6. **Fewer zooms = better** — 3 deliberate zooms beat 9 reactive ones.
7. **Demo Director bounding boxes need verification** — the agent estimates from
   thumbnails. A second verification agent reading full-res frames at zoom timestamps
   must correct the coordinates before applying the zoom script.
8. **OpenAI TTS `nova` voice is excellent for demos** — dramatically better than
   macOS `say`. But always ask the user their preference first.
9. **Voiceover should lead, not follow** — narrate what's about to happen 1-2s
   before it appears on screen. Include deliberate silence beats for reveals.
10. **Never start zoomed** — video must open with 3+ seconds of full wide view.
    If the Demo Director places a zoom at t=0, shift it to t=3.
11. **TTS duration varies by voice** — OpenAI `fable` speaks ~15% slower than
    `nova`. Always measure actual audio duration after generation and rebuild
    timestamps sequentially to prevent overlaps. Never trust the Demo Director's
    estimated `start_time` values — they're based on estimated duration, not actual.
12. **Auto-calculate zoom from bounding box** — don't use a fixed zoom level with
    a center point. Instead, compute the view rectangle directly from the `target_box`
    with padding, adjusted to output aspect ratio. This naturally centers the element
    and picks the right zoom level.
13. **Narration-first integrated timeline (v4.0)** — never overlay voiceover on a
    continuously-playing video. Build the video from the narration outward: for each
    narration segment, freeze the source on the relevant frame, play the narration,
    then advance to the next scene. The output is longer than the source (source +
    ~40% hold time) but narration and visuals are perfectly synchronized.
14. **Bounding boxes must be 2000-3000px wide** in a 6016px frame for visible zoom.
    Boxes of 4000+ px produce imperceptible zoom (~1.2x). Target the content column,
    not the full browser window.
