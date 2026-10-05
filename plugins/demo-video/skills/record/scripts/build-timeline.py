#!/usr/bin/env python3
"""Build integrated timeline: PLAY + HOLD_NARRATE segments.

Reads zoom-script.json (with hold_frames) and tts-manifest.json (with actual durations).
Outputs an integrated timeline that the renderer uses to create the final video.
"""
import json
import os

# Load inputs
with open(os.path.expanduser("~/Desktop/zoom-analysis/zoom-script.json")) as f:
    zoom = json.load(f)

with open(os.path.expanduser("~/Desktop/zoom-analysis/tts/tts-manifest.json")) as f:
    tts_segments = json.load(f)

with open(os.path.expanduser("~/Desktop/zoom-analysis/voiceover-script.json")) as f:
    voiceover = json.load(f)

trim_start = zoom["trim"]["start"]
trim_end = zoom["trim"]["end"]
source_duration = trim_end - trim_start  # 97.5s

hold_frames = sorted(zoom["hold_frames"], key=lambda h: h["source_time"])

# Map TTS segments to hold_frames by matching source_time proximity
# The voiceover script has segments with start_time (output timeline),
# and hold_frames have source_time. We need to pair speech with holds.

# Strategy: Build timeline sequentially through source time.
# At each hold point, insert a HOLD_NARRATE with the appropriate TTS segments.
# Between holds, insert PLAY segments.

# First, assign TTS segments to hold frames based on the voiceover structure
# The voiceover has segments at specific output times. We need to figure out
# which speech segments correspond to which hold frames.

# Build a mapping: for each hold, collect the speech segments that should play during it
# We do this by walking through the voiceover timeline and matching output times to holds

# Step 1: Build sequential output timeline to map speech to holds
# Each hold adds time to the output. We walk through source time and accumulate.
tts_by_id = {s["id"]: s for s in tts_segments}

# Assign speech segments to holds based on chronological order
# Hold 0 (source_time=2.0): Opening narration (seg_00)
# Hold 1 (source_time=19.0): Interests description (seg_06, seg_07)  
# Hold 2 (source_time=28.0): Generation moment (seg_09, seg_11)
# Hold 3 (source_time=48.0): Itinerary reveal (seg_13, seg_15)
# Hold 4 (source_time=58.0): Excursion cards (seg_17, seg_18)
# Hold 5 (source_time=76.0): Expanded detail (seg_20, seg_21)

# Let's be more systematic: assign speech to holds + inter-hold gaps
# Group speech segments by where they fall in the narrative

speech_groups = [
    # Group for Hold 0 (landing hero): intro segments
    {"hold_idx": 0, "segments": ["seg_00"]},
    # Questionnaire walkthrough (play between holds 0 and 1)
    {"play_after_hold": 0, "segments": ["seg_02", "seg_03", "seg_04"]},
    # Group for Hold 1 (interests): interest selection narration
    {"hold_idx": 1, "segments": ["seg_06", "seg_07"]},
    # Group for Hold 2 (streaming): generation narration
    {"hold_idx": 2, "segments": ["seg_09", "seg_11"]},
    # Group for Hold 3 (content reveal): reveal narration
    {"hold_idx": 3, "segments": ["seg_13", "seg_15"]},
    # Group for Hold 4 (detail cards): detail narration
    {"hold_idx": 4, "segments": ["seg_17", "seg_18"]},
    # Group for Hold 5 (expanded detail): deep dive
    {"hold_idx": 5, "segments": ["seg_20", "seg_21"]},
    # Outro narration (after all holds)
    {"play_after_hold": 5, "segments": ["seg_23", "seg_24", "seg_26", "seg_28"]},
]

# Build the integrated timeline
timeline = []
tts_placement = []  # {file, output_time, duration}
output_time = 0.0
last_source_time = 0.0

# Helper to get total duration of speech segments for a group
def group_speech_duration(seg_ids):
    total = 0.0
    for sid in seg_ids:
        if sid in tts_by_id:
            total += tts_by_id[sid]["actual_duration"]
    # Add 0.5s gaps between segments
    if len(seg_ids) > 1:
        total += (len(seg_ids) - 1) * 0.5
    return total + 0.3  # 0.3s buffer

# Process each hold in order
for hold_idx, hold in enumerate(hold_frames):
    source_time = hold["source_time"]
    
    # PLAY segment: advance from last source time to this hold point
    play_duration_source = source_time - last_source_time
    if play_duration_source > 0:
        # Compress play to max 2s per segment (viewers don't need real-time scrolling)
        play_duration = min(play_duration_source, max(1.5, play_duration_source * 0.3))
        
        # Check if there are "play_after_hold" speech groups for the previous hold
        play_speech = None
        for group in speech_groups:
            if group.get("play_after_hold") == hold_idx - 1:
                play_speech = group
                break
        
        if play_speech:
            # Play with speech overlay — extend play to cover the speech
            speech_dur = group_speech_duration(play_speech["segments"])
            play_duration = max(play_duration, speech_dur)
            
            # Place TTS during this play segment
            seg_offset = 0.0
            for sid in play_speech["segments"]:
                if sid in tts_by_id:
                    tts_placement.append({
                        "file": tts_by_id[sid]["file"],
                        "output_time": output_time + seg_offset,
                        "duration": tts_by_id[sid]["actual_duration"]
                    })
                    seg_offset += tts_by_id[sid]["actual_duration"] + 0.5
        
        timeline.append({
            "type": "play",
            "source_start": last_source_time,
            "source_end": source_time,
            "duration": play_duration,
            "description": f"Play source {last_source_time:.1f}s → {source_time:.1f}s"
        })
        output_time += play_duration
    
    # Find speech segments for this hold
    hold_speech_ids = []
    for group in speech_groups:
        if group.get("hold_idx") == hold_idx:
            hold_speech_ids = group["segments"]
            break
    
    # Calculate hold duration based on actual TTS duration
    if hold_speech_ids:
        actual_speech_dur = group_speech_duration(hold_speech_ids)
        hold_duration = max(hold["hold_duration"], actual_speech_dur)
    else:
        hold_duration = hold["hold_duration"]
    
    # HOLD_NARRATE segment
    timeline.append({
        "type": "hold_narrate",
        "source_time": source_time,
        "hold_duration": hold_duration,
        "segments": hold_speech_ids,
        "description": hold["description"]
    })
    
    # Place TTS during this hold
    seg_offset = 0.3  # Small delay before speech starts
    for sid in hold_speech_ids:
        if sid in tts_by_id:
            tts_placement.append({
                "file": tts_by_id[sid]["file"],
                "output_time": output_time + seg_offset,
                "duration": tts_by_id[sid]["actual_duration"]
            })
            seg_offset += tts_by_id[sid]["actual_duration"] + 0.5
    
    output_time += hold_duration
    last_source_time = source_time + 1.0  # Skip 1s after hold (slight advance)

# Final PLAY to end of source
remaining_source = source_duration - last_source_time
if remaining_source > 0:
    play_duration = min(remaining_source, max(2.0, remaining_source * 0.3))
    
    # Check for outro speech
    for group in speech_groups:
        if group.get("play_after_hold") == len(hold_frames) - 1:
            speech_dur = group_speech_duration(group["segments"])
            play_duration = max(play_duration, speech_dur)
            seg_offset = 0.0
            for sid in group["segments"]:
                if sid in tts_by_id:
                    tts_placement.append({
                        "file": tts_by_id[sid]["file"],
                        "output_time": output_time + seg_offset,
                        "duration": tts_by_id[sid]["actual_duration"]
                    })
                    seg_offset += tts_by_id[sid]["actual_duration"] + 0.5
            break
    
    timeline.append({
        "type": "play",
        "source_start": last_source_time,
        "source_end": source_duration,
        "duration": play_duration,
        "description": f"Final play {last_source_time:.1f}s → {source_duration:.1f}s (outro)"
    })
    output_time += play_duration

# Save timeline
timeline_path = os.path.expanduser("~/Desktop/zoom-analysis/integrated-timeline.json")
with open(timeline_path, "w") as f:
    json.dump({
        "source_duration": source_duration,
        "output_duration": output_time,
        "timeline": timeline,
        "tts_placement": tts_placement
    }, f, indent=2)

print(f"Source duration: {source_duration:.1f}s")
print(f"Output duration: {output_time:.1f}s (+{((output_time/source_duration)-1)*100:.0f}%)")
print(f"Timeline segments: {len(timeline)}")
print(f"  PLAY: {sum(1 for t in timeline if t['type'] == 'play')}")
print(f"  HOLD: {sum(1 for t in timeline if t['type'] == 'hold_narrate')}")
print(f"TTS placements: {len(tts_placement)}")
print(f"Saved: {timeline_path}")

# Print timeline summary
print("\n--- Timeline ---")
for i, seg in enumerate(timeline):
    if seg["type"] == "play":
        print(f"  [{i}] PLAY  {seg['duration']:.1f}s  (src {seg['source_start']:.1f}→{seg['source_end']:.1f})")
    else:
        print(f"  [{i}] HOLD  {seg['hold_duration']:.1f}s  at src={seg['source_time']:.1f}  segs={seg.get('segments', [])}")
