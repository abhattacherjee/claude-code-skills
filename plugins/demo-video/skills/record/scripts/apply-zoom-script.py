#!/usr/bin/env python3
"""Apply an AI-generated zoom script to a screen recording.

Reads a zoom-script.json with deliberate zoom events and applies them to produce
a polished output video. Supports:
  - Trim (start/end)
  - Bounding-box zoom targets (target_box) — centers the UI element in frame
  - Smooth ease-in-out transitions
  - 4K output resolution
"""
import argparse
import json
import subprocess
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    print("Missing: pip3 install opencv-python numpy", file=sys.stderr)
    sys.exit(1)


def smooth_step(t):
    """Ease-in-out: 3t^2 - 2t^3"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def load_zoom_script(path):
    with open(path) as f:
        return json.load(f)


def get_view_rect(events, t, in_w, in_h, out_aspect):
    """Determine the view rectangle (x, y, w, h) at time t.

    Returns the crop window in source frame coordinates.
    For target_box events: frames the bounding box with padding, maintaining output aspect ratio.
    Between events: full frame.
    """
    # Full frame view (default)
    full_view = (0, 0, in_w, in_h)

    for event in events:
        start = event["start"]
        end = event["end"]
        trans_in = event.get("transition_in", 2.0)
        trans_out = event.get("transition_out", 2.0)

        # Don't start transition before t=0 — clamp transition_in
        effective_trans_in = min(trans_in, start)

        # Calculate the target view for this event
        target_box = event.get("target_box")
        if target_box:
            # Frame the bounding box with padding, maintaining aspect ratio
            bx, by, bw, bh = target_box["x"], target_box["y"], target_box["w"], target_box["h"]
            # Add 15% padding
            pad_x = int(bw * 0.15)
            pad_y = int(bh * 0.15)
            padded_w = bw + 2 * pad_x
            padded_h = bh + 2 * pad_y
            padded_cx = bx + bw // 2
            padded_cy = by + bh // 2

            # Adjust to match output aspect ratio
            box_aspect = padded_w / padded_h
            if box_aspect > out_aspect:
                # Box is wider than output — expand height
                view_w = padded_w
                view_h = int(padded_w / out_aspect)
            else:
                # Box is taller than output — expand width
                view_h = padded_h
                view_w = int(padded_h * out_aspect)

            # Ensure even dimensions
            view_w = view_w + (view_w % 2)
            view_h = view_h + (view_h % 2)

            # Center on the box
            view_x = padded_cx - view_w // 2
            view_y = padded_cy - view_h // 2

            # Clamp to frame
            view_x = max(0, min(view_x, in_w - view_w))
            view_y = max(0, min(view_y, in_h - view_h))

            # Safety: ensure view fits in frame
            view_w = min(view_w, in_w)
            view_h = min(view_h, in_h)

            target_view = (view_x, view_y, view_w, view_h)
        else:
            target_view = full_view

        # Before this event's transition window
        if t < start - effective_trans_in:
            continue

        # During transition IN
        if t < start:
            progress = smooth_step((t - (start - effective_trans_in)) / effective_trans_in) if effective_trans_in > 0 else 1.0
            return blend_views(full_view, target_view, progress)

        # During the event
        if t <= end:
            return target_view

        # During transition OUT
        if t < end + trans_out:
            progress = smooth_step((t - end) / trans_out)
            return blend_views(target_view, full_view, progress)

    return full_view


def blend_views(view_a, view_b, progress):
    """Linearly blend two view rectangles."""
    ax, ay, aw, ah = view_a
    bx, by, bw, bh = view_b
    x = int(ax + progress * (bx - ax))
    y = int(ay + progress * (by - ay))
    w = int(aw + progress * (bw - aw))
    h = int(ah + progress * (bh - ah))
    # Ensure even
    w = w + (w % 2)
    h = h + (h % 2)
    return (x, y, w, h)


def process_video(input_path, script_path, output_path, out_w, out_h):
    """Apply zoom script to video."""
    script = load_zoom_script(script_path)
    events = script["events"]
    out_aspect = out_w / out_h

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error: cannot open {input_path}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Apply trim
    trim = script.get("trim")
    if trim:
        trim_start = trim.get("start", 0)
        trim_end = trim.get("end", total_frames / fps)
        start_frame = int(trim_start * fps)
        end_frame = int(trim_end * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        total_output_frames = end_frame - start_frame
        print(f"  Trim:   {trim_start}s - {trim_end}s ({total_output_frames} frames)", file=sys.stderr)
    else:
        trim_start = 0
        start_frame = 0
        end_frame = total_frames
        total_output_frames = total_frames

    # Parse hold_frames — points where we freeze the video for narration
    hold_frames = script.get("hold_frames", [])
    hold_frames.sort(key=lambda h: h["source_time"])
    total_hold_duration = sum(h["hold_duration"] for h in hold_frames)

    zoom_count = sum(1 for e in events if e.get("target_box"))
    print(f"  Input:  {in_w}x{in_h} @ {fps:.0f}fps", file=sys.stderr)
    print(f"  Output: {out_w}x{out_h}", file=sys.stderr)
    print(f"  Events: {len(events)} ({zoom_count} zooms)", file=sys.stderr)
    if hold_frames:
        print(f"  Holds:  {len(hold_frames)} freeze points ({total_hold_duration:.1f}s total)", file=sys.stderr)
        estimated_output = (total_output_frames / fps) + total_hold_duration
        print(f"  Est. output duration: {estimated_output:.1f}s", file=sys.stderr)

    # Open ffmpeg encoder
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{out_w}x{out_h}", "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        output_path,
    ]
    encoder = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    frame_idx = 0
    output_frame_count = 0
    hold_idx = 0  # next hold to process

    while frame_idx < total_output_frames:
        ret, frame = cap.read()
        if not ret:
            break

        source_t = frame_idx / fps  # time in trimmed source

        # Get view rectangle (zoom events use source_t)
        vx, vy, vw, vh = get_view_rect(events, source_t, in_w, in_h, out_aspect)

        # Safety clamp
        vx = max(0, min(vx, in_w - 2))
        vy = max(0, min(vy, in_h - 2))
        vw = max(2, min(vw, in_w - vx))
        vh = max(2, min(vh, in_h - vy))

        # Crop and resize
        cropped = frame[vy:vy + vh, vx:vx + vw]
        if cropped.size == 0:
            cropped = frame
        resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        frame_bytes = resized.tobytes()

        # Write the frame
        try:
            encoder.stdin.write(frame_bytes)
            output_frame_count += 1
        except BrokenPipeError:
            break

        # Check if we need to hold (freeze) at this source time
        if hold_idx < len(hold_frames):
            hold = hold_frames[hold_idx]
            if abs(source_t - hold["source_time"]) < 0.5 / fps:  # within half a frame
                hold_frame_count = int(hold["hold_duration"] * fps)
                desc = hold.get("description", "")
                print(f"\n  HOLD at source t={source_t:.1f}s for {hold['hold_duration']:.1f}s ({hold_frame_count} frames) — {desc[:50]}", file=sys.stderr)
                for _ in range(hold_frame_count):
                    try:
                        encoder.stdin.write(frame_bytes)
                        output_frame_count += 1
                    except BrokenPipeError:
                        break
                hold_idx += 1

        if frame_idx % max(1, int(fps)) == 0:
            est_total = total_output_frames + int(total_hold_duration * fps)
            pct = (output_frame_count / est_total * 100) if est_total > 0 else 0
            zoom_level = (in_w * in_h) / (vw * vh) if vw > 0 and vh > 0 else 1.0
            zoom_level = zoom_level ** 0.5
            print(f"\r  Processing: {pct:5.1f}%  src {frame_idx}/{total_output_frames}  out {output_frame_count}  zoom {zoom_level:.1f}x    ", end="", file=sys.stderr)

        frame_idx += 1

    encoder.stdin.close()
    encoder.wait()
    cap.release()

    if encoder.returncode != 0:
        print(f"\nError: ffmpeg exited with code {encoder.returncode}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Done: {output_path} ({frame_idx} frames)", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply AI-generated zoom script to a screen recording")
    parser.add_argument("video", help="Input video file")
    parser.add_argument("script", help="Zoom script JSON file")
    parser.add_argument("-o", "--output", required=True, help="Output video file")
    parser.add_argument("--resolution", default="3840x2160", help="Output resolution (default: 3840x2160)")
    args = parser.parse_args()

    out_w, out_h = map(int, args.resolution.split("x"))
    process_video(args.video, args.script, args.output, out_w, out_h)
