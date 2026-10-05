#!/usr/bin/env python3
"""Generate TTS audio for all speech segments using the OpenAI API.

Reads ~/Desktop/zoom-analysis/voiceover-script.json and writes one mp3 per
segment, plus tts-manifest.json, to ~/Desktop/zoom-analysis/tts. OpenAI only.
The API key is sent in a request header from this process, never on a command
line. OPENAI_BASE_URL, if set, replaces https://api.openai.com/v1.
Exits 1 if any segment failed, after writing the manifest for the rest.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

SCRIPT_PATH = os.path.expanduser("~/Desktop/zoom-analysis/voiceover-script.json")
OUT_DIR = os.path.expanduser("~/Desktop/zoom-analysis/tts")
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_script():
    try:
        with open(SCRIPT_PATH) as f:
            script = json.load(f)
    except FileNotFoundError:
        fail(f"voiceover script not found: {SCRIPT_PATH}")
    except ValueError as e:
        fail(f"voiceover script is not valid JSON: {SCRIPT_PATH}: {e}")
    if not isinstance(script, dict) or not isinstance(script.get("segments"), list) or not script.get("voice"):
        fail(f"{SCRIPT_PATH} needs a \"voice\" and a \"segments\" list")
    # Check every segment before any request. The id becomes a file name.
    problems = []
    for n, seg in enumerate(script["segments"], 1):
        if not isinstance(seg, dict):
            problems.append(f"segment {n} is not an object")
            continue
        seg_id = seg.get("id")
        if not isinstance(seg_id, str) or not SAFE_ID.fullmatch(seg_id):
            problems.append(f"segment {n}: id {seg_id!r} must be letters, digits, _ or -")
        if not isinstance(seg.get("text"), str):
            problems.append(f"segment {n} ({seg_id}): \"text\" must be a string (\"\" for a silence beat)")
        for key in ("duration", "start_time"):
            if not isinstance(seg.get(key), (int, float)):
                problems.append(f"segment {n} ({seg_id}): \"{key}\" must be a number")
    if problems:
        fail(f"{SCRIPT_PATH} has bad segments:\n  " + "\n  ".join(problems))
    return script


def speech(api_key, voice, text):
    """POST one TTS request. Returns the mp3 bytes; raises RuntimeError with the reason."""
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    body = json.dumps({"model": "tts-1-hd", "voice": voice, "input": text, "response_format": "mp3"}).encode()
    req = urllib.request.Request(base + "/audio/speech", data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"request failed: {e}") from None
    if not data:
        raise RuntimeError("empty response")
    return data


def measured_duration(path, estimate):
    """The mp3's length from ffprobe, or the estimate (with a warning) when it cannot be read."""
    try:
        result = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
                                capture_output=True, text=True)
        return float(json.loads(result.stdout)["format"]["duration"])
    except FileNotFoundError:
        why = "ffprobe is not installed"
    except (ValueError, KeyError, TypeError):
        why = "ffprobe could not read it"
    print(f"    Warning: {why}; using the estimated {estimate}s for {os.path.basename(path)}", file=sys.stderr)
    return float(estimate)


def main():
    script = load_script()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fail("OPENAI_API_KEY not set")
    voice = script["voice"]
    os.makedirs(OUT_DIR, exist_ok=True)

    segments_with_audio = []
    failed = []
    spoken = [seg for seg in script["segments"] if seg["text"].strip()]  # "" is a silence beat
    for seg in spoken:
        seg_id = seg["id"]
        out_file = os.path.join(OUT_DIR, f"{seg_id}.mp3")
        print(f"  Generating TTS: {seg_id} — {seg['text'][:50]}...", file=sys.stderr)
        try:
            audio = speech(api_key, voice, seg["text"])
        except RuntimeError as e:
            print(f"  ERROR generating {seg_id}: {e}", file=sys.stderr)
            failed.append(seg_id)
            continue
        # Only a successful response is saved, so an error body never becomes an mp3.
        with open(out_file, "wb") as f:
            f.write(audio)
        actual_duration = measured_duration(out_file, seg["duration"])
        segments_with_audio.append({
            "id": seg_id,
            "file": out_file,
            "text": seg["text"],
            "estimated_duration": seg["duration"],
            "actual_duration": actual_duration,
            "original_start_time": seg["start_time"],
        })
        print(f"    OK: {actual_duration:.1f}s (estimated {seg['duration']}s)", file=sys.stderr)

    # Save manifest with actual durations
    manifest_path = os.path.join(OUT_DIR, "tts-manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(segments_with_audio, f, indent=2)

    print(f"\n  Generated {len(segments_with_audio)} TTS segments", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    total_speech = sum(s["actual_duration"] for s in segments_with_audio)
    print(f"  Total speech: {total_speech:.1f}s", file=sys.stderr)
    if failed:
        fail(f"{len(failed)} of {len(spoken)} segments failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
