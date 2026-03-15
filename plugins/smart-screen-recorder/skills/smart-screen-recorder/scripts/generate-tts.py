#!/usr/bin/env python3
"""Generate TTS audio for all speech segments using OpenAI API."""
import json
import os
import sys
import subprocess

# Read voiceover script
with open(os.path.expanduser("~/Desktop/zoom-analysis/voiceover-script.json")) as f:
    script = json.load(f)

voice = script["voice"]
out_dir = os.path.expanduser("~/Desktop/zoom-analysis/tts")
os.makedirs(out_dir, exist_ok=True)

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
    sys.exit(1)

segments_with_audio = []
for seg in script["segments"]:
    if not seg["text"].strip():
        # Silence segment — no TTS needed
        continue
    
    seg_id = seg["id"]
    out_file = os.path.join(out_dir, f"{seg_id}.mp3")
    
    print(f"  Generating TTS: {seg_id} — {seg['text'][:50]}...", file=sys.stderr)
    
    # Use curl to call OpenAI TTS API
    result = subprocess.run([
        "curl", "-s", "-X", "POST",
        "https://api.openai.com/v1/audio/speech",
        "-H", f"Authorization: Bearer {api_key}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({
            "model": "tts-1-hd",
            "voice": voice,
            "input": seg["text"],
            "response_format": "mp3"
        }),
        "-o", out_file
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  ERROR generating {seg_id}: {result.stderr}", file=sys.stderr)
        continue
    
    # Check file size (error responses are small JSON)
    file_size = os.path.getsize(out_file)
    if file_size < 1000:
        with open(out_file, 'r', errors='replace') as ef:
            content = ef.read(200)
        if '"error"' in content:
            print(f"  ERROR: API error for {seg_id}: {content}", file=sys.stderr)
            continue
    
    # Get actual duration using ffprobe
    dur_result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", out_file
    ], capture_output=True, text=True)
    
    try:
        dur_info = json.loads(dur_result.stdout)
        actual_duration = float(dur_info["format"]["duration"])
    except:
        actual_duration = seg["duration"]
    
    segments_with_audio.append({
        "id": seg_id,
        "file": out_file,
        "text": seg["text"],
        "estimated_duration": seg["duration"],
        "actual_duration": actual_duration,
        "original_start_time": seg["start_time"]
    })
    
    print(f"    OK: {actual_duration:.1f}s (estimated {seg['duration']}s)", file=sys.stderr)

# Save manifest with actual durations
manifest_path = os.path.join(out_dir, "tts-manifest.json")
with open(manifest_path, "w") as f:
    json.dump(segments_with_audio, f, indent=2)

print(f"\n  Generated {len(segments_with_audio)} TTS segments", file=sys.stderr)
print(f"  Manifest: {manifest_path}", file=sys.stderr)
total_speech = sum(s["actual_duration"] for s in segments_with_audio)
print(f"  Total speech: {total_speech:.1f}s", file=sys.stderr)
