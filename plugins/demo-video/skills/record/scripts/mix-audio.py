#!/usr/bin/env python3
"""Mix TTS audio segments into the rendered video at precise timestamps.

Reads ~/Desktop/zoom-analysis/integrated-timeline.json and ~/Desktop/demo-video-only.mp4,
writes ~/Desktop/demo-final.mp4. Exits 1 if any ffmpeg step fails. An old
demo-final.mp4 is removed first, so it can never pass for this run's output.
"""
import json
import os
import subprocess
import sys

TIMELINE = os.path.expanduser("~/Desktop/zoom-analysis/integrated-timeline.json")
VIDEO = os.path.expanduser("~/Desktop/demo-video-only.mp4")
OUTPUT = os.path.expanduser("~/Desktop/demo-final.mp4")
TTS_DIR = os.path.expanduser("~/Desktop/zoom-analysis/tts")


def fail(msg):
    print(f"\n  ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, what):
    """Run one ffmpeg/ffprobe step; stop with its error output if it fails."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        fail(f"{cmd[0]} is not installed (brew install ffmpeg)")
    if result.returncode != 0:
        fail(f"{what} failed (exit {result.returncode}): {result.stderr.strip()[-500:]}")
    return result


try:
    with open(TIMELINE) as f:
        data = json.load(f)
except FileNotFoundError:
    fail(f"timeline not found: {TIMELINE} (run build-timeline.py first)")
except ValueError as e:
    fail(f"timeline is not valid JSON: {TIMELINE}: {e}")

tts_placement = data.get("tts_placement") if isinstance(data, dict) else None

if not tts_placement:
    print("No TTS segments to mix!", file=sys.stderr)
    sys.exit(1)
if not os.path.isfile(VIDEO):
    fail(f"video not found: {VIDEO} (run render-timeline.py first)")
missing = [p["file"] for p in tts_placement if not os.path.isfile(p["file"])]
if missing:
    fail("TTS files not found: " + ", ".join(missing))

# An output left from an earlier run must not look like this run's result.
if os.path.exists(OUTPUT):
    os.remove(OUTPUT)

print(f"Mixing {len(tts_placement)} audio segments into video...", file=sys.stderr)

# Build ffmpeg complex filter for mixing audio
# Strategy: concat all TTS with silence padding, then merge with video
# Use adelay to place each segment at its output_time

inputs = ["-i", VIDEO]
filter_parts = []

for i, placement in enumerate(tts_placement):
    inputs.extend(["-i", placement["file"]])
    delay_ms = int(placement["output_time"] * 1000)
    # adelay: delay audio by N ms (for both channels)
    filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[a{i}]")
    print(f"  {placement['file'].split('/')[-1]} @ {placement['output_time']:.1f}s (delay {delay_ms}ms)", file=sys.stderr)

# Mix all delayed audio together
audio_labels = "".join(f"[a{i}]" for i in range(len(tts_placement)))
filter_parts.append(f"{audio_labels}amix=inputs={len(tts_placement)}:duration=longest:dropout_transition=0[mixed]")

# Normalize audio volume (amix reduces volume)
filter_parts.append(f"[mixed]volume={min(len(tts_placement), 8)}[aout]")

filter_complex = ";".join(filter_parts)

cmd = [
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
    *inputs,
    "-filter_complex", filter_complex,
    "-map", "0:v",
    "-map", "[aout]",
    "-c:v", "copy",  # Don't re-encode video
    "-c:a", "aac", "-b:a", "192k",
    "-shortest",
    OUTPUT
]

print("\nRunning ffmpeg audio mix...", file=sys.stderr)
try:
    result = subprocess.run(cmd, capture_output=True, text=True)
except FileNotFoundError:
    fail("ffmpeg is not installed (brew install ffmpeg)")

if result.returncode != 0:
    print(f"ffmpeg error: {result.stderr}", file=sys.stderr)
    # Try simpler approach if complex filter fails
    print("\nTrying simpler sequential approach...", file=sys.stderr)
    if os.path.exists(OUTPUT):
        os.remove(OUTPUT)

    # Generate a silent audio track, then overlay each segment
    # First, create silent base audio matching video duration
    dur_result = run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", VIDEO],
                     "ffprobe of the video")
    try:
        video_dur = float(json.loads(dur_result.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        fail(f"ffprobe gave no duration for {VIDEO}")

    # Create silent audio
    silent = os.path.join(TTS_DIR, "silent.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", str(video_dur),
         silent], "making the silent track")

    # Overlay each TTS segment onto the silent track one at a time
    current_audio = silent
    for i, placement in enumerate(tts_placement):
        next_audio = os.path.join(TTS_DIR, f"mix_{i}.wav")
        delay_ms = int(placement["output_time"] * 1000)
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", current_audio,
             "-i", placement["file"],
             "-filter_complex",
             f"[1:a]adelay={delay_ms}|{delay_ms}[delayed];[0:a][delayed]amix=inputs=2:duration=first:dropout_transition=0,volume=2[out]",
             "-map", "[out]",
             next_audio], f"mixing in {os.path.basename(placement['file'])}")
        if current_audio != silent:
            os.remove(current_audio)
        current_audio = next_audio
        print(f"  Mixed {i+1}/{len(tts_placement)}: {placement['file'].split('/')[-1]}", file=sys.stderr)

    # Merge final audio with video
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", VIDEO,
         "-i", current_audio,
         "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k",
         "-map", "0:v", "-map", "1:a",
         "-shortest",
         OUTPUT], "merging the audio with the video")
    os.remove(current_audio)
    if os.path.exists(silent):
        os.remove(silent)

if not os.path.isfile(OUTPUT) or os.path.getsize(OUTPUT) == 0:
    fail(f"ffmpeg reported success but wrote no {OUTPUT}")
size = os.path.getsize(OUTPUT) / (1024*1024)
print(f"\n  Final output: {OUTPUT} ({size:.1f}MB)", file=sys.stderr)
