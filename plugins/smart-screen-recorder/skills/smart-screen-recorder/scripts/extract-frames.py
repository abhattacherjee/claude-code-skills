#!/usr/bin/env python3
"""Extract key frames from a screen recording for AI analysis.

Identifies "interaction moments" from the cursor log (pauses, clicks, large jumps)
and extracts those video frames as numbered PNG images. Also produces a manifest
JSON that pairs each frame with its cursor context.

Output:
  {output_dir}/
    frames/
      frame_001_t12.5.png    — video frame at t=12.5s
      frame_002_t18.3.png    — ...
    manifest.json            — [{frame, time, cursor, reason, window_bounds}, ...]
"""
import argparse
import json
import math
import os
import sys

try:
    import cv2
except ImportError:
    print("Missing: pip3 install opencv-python", file=sys.stderr)
    sys.exit(1)


def load_cursor_log(path):
    """Parse JSONL into header, positions, clicks, windows."""
    header = None
    positions = []
    clicks = []
    windows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            t = data.get("type")
            if t == "header":
                header = data
            elif t == "window":
                windows.append(data)
            elif "click" in data:
                clicks.append(data)
            else:
                positions.append(data)
    return header, positions, clicks, windows


def find_interaction_moments(positions, clicks, min_pause=0.6, min_jump=300):
    """Identify moments worth extracting frames for.

    Returns list of {t, x, y, reason} sorted by time.
    """
    moments = []

    # 1. Find cursor pauses (still for min_pause seconds)
    if len(positions) > 1:
        still_start = positions[0]["t"]
        still_x, still_y = positions[0]["x"], positions[0]["y"]

        for i in range(1, len(positions)):
            p = positions[i]
            dx = p["x"] - still_x
            dy = p["y"] - still_y
            dist = math.sqrt(dx * dx + dy * dy)

            if dist > 40:  # cursor moved
                if p["t"] - still_start >= min_pause:
                    # Was paused long enough — record the midpoint of the pause
                    mid_t = (still_start + positions[i - 1]["t"]) / 2
                    moments.append({
                        "t": round(mid_t, 2),
                        "x": round(still_x),
                        "y": round(still_y),
                        "reason": f"cursor_pause ({positions[i-1]['t'] - still_start:.1f}s)",
                    })
                still_start = p["t"]
                still_x, still_y = p["x"], p["y"]

    # 2. Add click events
    for c in clicks:
        moments.append({
            "t": round(c["t"], 2),
            "x": round(c["x"]),
            "y": round(c["y"]),
            "reason": f"click_{c['click']}",
        })

    # 3. Find large cursor jumps (navigation/scroll events)
    if len(positions) > 1:
        for i in range(1, len(positions)):
            p0, p1 = positions[i - 1], positions[i]
            dx = p1["x"] - p0["x"]
            dy = p1["y"] - p0["y"]
            dist = math.sqrt(dx * dx + dy * dy)
            dt = p1["t"] - p0["t"]
            if dt > 0 and dist > min_jump:
                # Large jump — extract frame AFTER the jump (new location)
                moments.append({
                    "t": round(p1["t"] + 0.3, 2),  # slightly after the jump
                    "x": round(p1["x"]),
                    "y": round(p1["y"]),
                    "reason": f"cursor_jump ({dist:.0f}px)",
                })

    # 4. Always include first and last frames
    if positions:
        moments.append({"t": 0.5, "x": round(positions[0]["x"]), "y": round(positions[0]["y"]), "reason": "start"})
        last = positions[-1]
        moments.append({"t": round(last["t"] - 0.5, 2), "x": round(last["x"]), "y": round(last["y"]), "reason": "end"})

    # Deduplicate — merge moments within 1.5s of each other
    moments.sort(key=lambda m: m["t"])
    deduped = []
    for m in moments:
        if not deduped or m["t"] - deduped[-1]["t"] > 1.5:
            deduped.append(m)
        else:
            # Keep the more interesting one (clicks > pauses > jumps)
            priority = {"click_left": 3, "click_right": 3, "start": 0, "end": 0}
            old_p = max(priority.get(deduped[-1]["reason"].split()[0], 1), 1)
            new_p = max(priority.get(m["reason"].split()[0], 1), 1)
            if new_p > old_p:
                deduped[-1] = m

    return deduped


def get_window_at_time(windows, t):
    """Get the active window bounds closest to time t."""
    if not windows:
        return None
    best = windows[0]
    for w in windows:
        if w["t"] <= t:
            best = w
        else:
            break
    return {"app": best.get("app"), "x": best["x"], "y": best["y"], "w": best["w"], "h": best["h"]}


def extract_frames(video_path, cursor_path, output_dir):
    """Extract key frames as PNG images with a manifest."""
    header, positions, clicks, windows = load_cursor_log(cursor_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: cannot open {video_path}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"  Video: {in_w}x{in_h}, {duration:.1f}s, {fps:.0f}fps", file=sys.stderr)
    print(f"  Cursor: {len(positions)} positions, {len(clicks)} clicks, {len(windows)} window snapshots", file=sys.stderr)

    # Find interaction moments
    moments = find_interaction_moments(positions, clicks)
    print(f"  Found {len(moments)} key moments to extract", file=sys.stderr)

    # Create output directory
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    manifest = []
    for idx, moment in enumerate(moments, 1):
        t = moment["t"]
        if t < 0 or t > duration:
            continue

        frame_num = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            continue

        # If we have window bounds, crop to the active window
        wb = get_window_at_time(windows, t)
        if wb and wb["w"] > 100 and wb["h"] > 100:
            wx, wy, ww, wh = wb["x"], wb["y"], wb["w"], wb["h"]
            # Clamp to frame
            wx = max(0, min(wx, in_w - 10))
            wy = max(0, min(wy, in_h - 10))
            ww = min(ww, in_w - wx)
            wh = min(wh, in_h - wy)
            cropped = frame[wy:wy + wh, wx:wx + ww]
            if cropped.size > 0:
                frame = cropped

        # Save frame
        filename = f"frame_{idx:03d}_t{t:.1f}.png"
        filepath = os.path.join(frames_dir, filename)

        # Resize to reasonable size for AI analysis (max 1920px wide)
        h, w = frame.shape[:2]
        if w > 1920:
            scale = 1920 / w
            frame = cv2.resize(frame, (1920, int(h * scale)))

        cv2.imwrite(filepath, frame)

        entry = {
            "frame": filename,
            "index": idx,
            "time": t,
            "cursor": {"x": moment["x"], "y": moment["y"]},
            "reason": moment["reason"],
        }
        if wb:
            entry["window"] = wb
        manifest.append(entry)

        print(f"    [{idx:3d}] t={t:6.1f}s  reason={moment['reason']:30s}  → {filename}", file=sys.stderr)

    cap.release()

    # Save manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({
            "video": video_path,
            "cursor_log": cursor_path,
            "duration": round(duration, 2),
            "resolution": {"w": in_w, "h": in_h},
            "moments": manifest,
        }, f, indent=2)

    print(f"\n  Extracted {len(manifest)} frames to {frames_dir}/", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract key frames for AI zoom analysis")
    parser.add_argument("video", help="Input video file")
    parser.add_argument("cursor_log", help="Cursor position JSONL file")
    parser.add_argument("-o", "--output-dir", required=True, help="Output directory for frames + manifest")
    args = parser.parse_args()
    extract_frames(args.video, args.cursor_log, args.output_dir)
