# demo-video:record file formats

The scripts are the source of truth for these formats. All times are seconds on the
**trimmed** recording: 0 is `trim.start`.

## zoom-script.json

Written by the Demo Director, corrected by the Zoom QA Verifier, and read by
`apply-zoom-script.py`, `build-timeline.py` and `render-timeline.py`.

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
      "target_box": {"x": 1750, "y": 250, "w": 3000, "h": 1550},
      "target_element": "Interest selection grid with colorful tag pills",
      "transition_in": 2.5, "transition_out": 2.0
    }
  ],
  "hold_frames": [
    {"source_time": 33.0, "hold_duration": 8.0, "description": "Freeze on the overview while the narrator describes it"}
  ]
}
```

- `events`: the view is at `target_box` from `start` to `end`, eases in over the
  `transition_in` seconds before `start` and out over the `transition_out` seconds after `end`.
- `zoom` is a note only; no script reads it. The scripts compute the zoom from `target_box`:
  the box plus 15% padding on each side fills the frame, so a box about 16:9 in shape gives
  a zoom of about frame width / (1.3 × box width).
- `hold_frames`: freeze the video at `source_time` for at least `hold_duration` seconds while
  the narrator speaks. They belong in zoom-script.json, not in the voiceover script.

## voiceover-script.json

Written by the Demo Director and read by `generate-tts.py`.

```json
{
  "voice": "nova",
  "provider": "openai-tts",
  "segments": [
    {"id": "seg_00", "start_time": 0.0, "duration": 4.5, "text": "Narration text."},
    {"id": "seg_01", "start_time": 5.0, "duration": 2.0, "text": ""}
  ]
}
```

- `id` is required and becomes the file name (`seg_00.mp3`): letters, digits, `_` and `-` only.
- `text: ""` is a silence beat: no audio is made for it.
- `duration` is the Director's estimate; `generate-tts.py` measures the real one.
- `start_time` is where the Director plans the line, on the trimmed recording. No script places
  audio by it: `generate-tts.py` copies it into the manifest as `original_start_time`, and
  `build-timeline.py` places each clip inside a hold or play segment (SKILL.md Step 7).

## integrated-timeline.json

Written by `build-timeline.py`, read by `preview-timeline.py`, `render-timeline.py` and
`mix-audio.py`. `output_time` is on the output video, which is longer than the recording.

```json
{
  "source_duration": 98.0,
  "output_duration": 135.2,
  "timeline": [
    {"type": "play", "source_start": 0.0, "source_end": 5.0, "duration": 1.5, "description": "Play source 0.0s → 5.0s"},
    {"type": "hold_narrate", "source_time": 5.0, "hold_duration": 5.3, "segments": ["seg_00"], "description": "Landing hero"},
    {"type": "play", "source_start": 6.0, "source_end": 10.0, "duration": 1.5, "description": "Play source 6.0s → 10.0s"}
  ],
  "tts_placement": [
    {"file": "/Users/you/Desktop/zoom-analysis/tts/seg_00.mp3", "output_time": 1.8, "duration": 5.0}
  ]
}
```
