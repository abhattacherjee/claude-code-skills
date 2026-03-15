#!/usr/bin/env python3
"""Mix TTS audio segments into the rendered video at precise timestamps."""
import json
import os
import subprocess
import sys

with open(os.path.expanduser("~/Desktop/zoom-analysis/integrated-timeline.json")) as f:
    data = json.load(f)

tts_placement = data["tts_placement"]
VIDEO = os.path.expanduser("~/Desktop/demo-video-only.mp4")
OUTPUT = os.path.expanduser("~/Desktop/demo-final.mp4")

if not tts_placement:
    print("No TTS segments to mix!", file=sys.stderr)
    sys.exit(1)

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

print(f"\nRunning ffmpeg audio mix...", file=sys.stderr)
result = subprocess.run(cmd, capture_output=True, text=True)

if result.returncode != 0:
    print(f"ffmpeg error: {result.stderr}", file=sys.stderr)
    # Try simpler approach if complex filter fails
    print("\nTrying simpler sequential approach...", file=sys.stderr)
    
    # Generate a silent audio track, then overlay each segment
    # First, create silent base audio matching video duration
    dur_result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", VIDEO
    ], capture_output=True, text=True)
    video_dur = float(json.loads(dur_result.stdout)["format"]["duration"])
    
    # Create silent audio
    silent = os.path.expanduser("~/Desktop/zoom-analysis/tts/silent.wav")
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(video_dur),
        silent
    ])
    
    # Overlay each TTS segment onto the silent track one at a time
    current_audio = silent
    for i, placement in enumerate(tts_placement):
        next_audio = os.path.expanduser(f"~/Desktop/zoom-analysis/tts/mix_{i}.wav")
        delay_ms = int(placement["output_time"] * 1000)
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", current_audio,
            "-i", placement["file"],
            "-filter_complex",
            f"[1:a]adelay={delay_ms}|{delay_ms}[delayed];[0:a][delayed]amix=inputs=2:duration=first:dropout_transition=0,volume=2[out]",
            "-map", "[out]",
            next_audio
        ])
        if i > 0 and current_audio != silent:
            os.remove(current_audio)
        current_audio = next_audio
        print(f"  Mixed {i+1}/{len(tts_placement)}: {placement['file'].split('/')[-1]}", file=sys.stderr)
    
    # Merge final audio with video
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", VIDEO,
        "-i", current_audio,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v", "-map", "1:a",
        "-shortest",
        OUTPUT
    ])
    os.remove(current_audio)

if os.path.exists(OUTPUT):
    size = os.path.getsize(OUTPUT) / (1024*1024)
    print(f"\n  Final output: {OUTPUT} ({size:.1f}MB)", file=sys.stderr)
else:
    print(f"\n  ERROR: Output not created!", file=sys.stderr)
    sys.exit(1)
