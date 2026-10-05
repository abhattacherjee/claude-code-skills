#!/usr/bin/env python3
"""Render integrated timeline: alternates PLAY and HOLD segments with zoom."""
import json
import os
import subprocess
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    print("Missing: pip3 install opencv-python numpy", file=sys.stderr)
    sys.exit(1)

# Load everything
with open(os.path.expanduser("~/Desktop/zoom-analysis/integrated-timeline.json")) as f:
    data = json.load(f)

with open(os.path.expanduser("~/Desktop/zoom-analysis/zoom-script.json")) as f:
    zoom_script = json.load(f)

timeline = data["timeline"]
tts_placement = data["tts_placement"]

RAW_VIDEO = os.path.expanduser("~/Desktop/screen-recording-20260315-084024-raw.mp4")
TRIM_START = zoom_script["trim"]["start"]
OUT_W, OUT_H = 3840, 2160
FPS = 30
OUTPUT_VIDEO = os.path.expanduser("~/Desktop/demo-video-only.mp4")

events = zoom_script["events"]
out_aspect = OUT_W / OUT_H

def smooth_step(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)

def get_view_rect(source_t, in_w, in_h):
    """Get crop rect at source_t (relative to trimmed start)."""
    full_view = (0, 0, in_w, in_h)
    for event in events:
        start = event["start"]
        end = event["end"]
        trans_in = event.get("transition_in", 2.0)
        trans_out = event.get("transition_out", 2.0)
        effective_trans_in = min(trans_in, start)
        
        tb = event.get("target_box")
        if tb:
            bx, by, bw, bh = tb["x"], tb["y"], tb["w"], tb["h"]
            pad_x, pad_y = int(bw * 0.15), int(bh * 0.15)
            pw, ph = bw + 2*pad_x, bh + 2*pad_y
            cx, cy = bx + bw//2, by + bh//2
            box_aspect = pw / ph
            if box_aspect > out_aspect:
                vw, vh = pw, int(pw / out_aspect)
            else:
                vh, vw = ph, int(ph * out_aspect)
            vw += vw % 2; vh += vh % 2
            vx = max(0, min(cx - vw//2, in_w - vw))
            vy = max(0, min(cy - vh//2, in_h - vh))
            vw = min(vw, in_w); vh = min(vh, in_h)
            target_view = (vx, vy, vw, vh)
        else:
            target_view = full_view
        
        if source_t < start - effective_trans_in:
            continue
        if source_t < start:
            p = smooth_step((source_t - (start - effective_trans_in)) / effective_trans_in) if effective_trans_in > 0 else 1.0
            return blend(full_view, target_view, p)
        if source_t <= end:
            return target_view
        if source_t < end + trans_out:
            p = smooth_step((source_t - end) / trans_out)
            return blend(target_view, full_view, p)
    return full_view

def blend(a, b, p):
    return (
        int(a[0] + p*(b[0]-a[0])),
        int(a[1] + p*(b[1]-a[1])),
        int(a[2] + p*(b[2]-a[2])) + (int(a[2] + p*(b[2]-a[2])) % 2),
        int(a[3] + p*(b[3]-a[3])) + (int(a[3] + p*(b[3]-a[3])) % 2)
    )

def crop_and_resize(frame, source_t, in_w, in_h):
    vx, vy, vw, vh = get_view_rect(source_t, in_w, in_h)
    vx = max(0, min(vx, in_w-2)); vy = max(0, min(vy, in_h-2))
    vw = max(2, min(vw, in_w-vx)); vh = max(2, min(vh, in_h-vy))
    cropped = frame[vy:vy+vh, vx:vx+vw]
    if cropped.size == 0:
        cropped = frame
    return cv2.resize(cropped, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)

# Open video
cap = cv2.VideoCapture(RAW_VIDEO)
in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
video_fps = cap.get(cv2.CAP_PROP_FPS) or 30

print(f"Input: {in_w}x{in_h} @ {video_fps:.0f}fps", file=sys.stderr)
print(f"Output: {OUT_W}x{OUT_H} @ {FPS}fps", file=sys.stderr)
print(f"Timeline segments: {len(timeline)}", file=sys.stderr)

# Open encoder
enc_cmd = [
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
    "-f", "rawvideo", "-pix_fmt", "bgr24",
    "-s", f"{OUT_W}x{OUT_H}", "-r", str(FPS),
    "-i", "-",
    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
    "-pix_fmt", "yuv420p",
    OUTPUT_VIDEO
]
encoder = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE)

output_frame_count = 0
total_est_frames = int(data["output_duration"] * FPS)

def write_frame(frame_bytes):
    global output_frame_count
    try:
        encoder.stdin.write(frame_bytes)
        output_frame_count += 1
    except BrokenPipeError:
        return False
    return True

def seek_and_read(source_time):
    """Seek to source_time (relative to trimmed start) and read frame."""
    abs_time = TRIM_START + source_time
    abs_frame = int(abs_time * video_fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, abs_frame)
    ret, frame = cap.read()
    return frame if ret else None

for seg_idx, seg in enumerate(timeline):
    pct = output_frame_count / total_est_frames * 100 if total_est_frames > 0 else 0
    print(f"\r  [{seg_idx+1}/{len(timeline)}] {seg['type']:12s} {pct:5.1f}%  frames={output_frame_count}", end="", file=sys.stderr)
    
    if seg["type"] == "play":
        src_start = seg["source_start"]
        src_end = seg["source_end"]
        src_duration = src_end - src_start
        out_duration = seg["duration"]
        out_frames = int(out_duration * FPS)
        
        # Read source frames, mapping output frames to source times
        for i in range(out_frames):
            # Map output frame to source time (may be compressed)
            t_ratio = i / max(1, out_frames - 1) if out_frames > 1 else 0
            source_t = src_start + t_ratio * src_duration
            
            frame = seek_and_read(source_t)
            if frame is None:
                break
            
            resized = crop_and_resize(frame, source_t, in_w, in_h)
            if not write_frame(resized.tobytes()):
                break
    
    elif seg["type"] == "hold_narrate":
        source_t = seg["source_time"]
        hold_duration = seg["hold_duration"]
        hold_frames_count = int(hold_duration * FPS)
        
        # Read the single frame to hold on
        frame = seek_and_read(source_t)
        if frame is None:
            continue
        
        resized = crop_and_resize(frame, source_t, in_w, in_h)
        frame_bytes = resized.tobytes()
        
        # Write the same frame repeatedly
        for _ in range(hold_frames_count):
            if not write_frame(frame_bytes):
                break

print(f"\n  Encoding complete: {output_frame_count} frames ({output_frame_count/FPS:.1f}s)", file=sys.stderr)

encoder.stdin.close()
encoder.wait()
cap.release()

if encoder.returncode != 0:
    print(f"Error: ffmpeg exited {encoder.returncode}", file=sys.stderr)
    sys.exit(1)

print(f"  Video saved: {OUTPUT_VIDEO}", file=sys.stderr)
