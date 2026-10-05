#!/usr/bin/env python3
"""Render integrated timeline: alternates PLAY and HOLD segments with zoom.

Exits 1 if the video does not open, or if any frame the timeline needs cannot be
read: then the output is shorter than the timeline and the narration, placed by
output time, drifts. The file is still written so you can look at it.
"""
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


def load_json(path):
    """Read one input file, or exit 1 with a one-line message."""
    path = os.path.expanduser(path)
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: input not found: {path}", file=sys.stderr)
    except ValueError as e:
        print(f"Error: {path} is not valid JSON: {e}", file=sys.stderr)
    sys.exit(1)


# Load everything
data = load_json("~/Desktop/zoom-analysis/integrated-timeline.json")
zoom_script = load_json("~/Desktop/zoom-analysis/zoom-script.json")

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
if not cap.isOpened():
    print(f"Error: cannot open the raw video {RAW_VIDEO}", file=sys.stderr)
    sys.exit(1)
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

problems = []  # one line per segment that came out short
holds_planned = sum(1 for seg in timeline if seg["type"] == "hold_narrate")
holds_rendered = 0

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
        written = 0
        for i in range(out_frames):
            # Map output frame to source time (may be compressed). The end of the
            # source interval is exclusive: the next segment starts there, so the
            # last frame samples one step before it. With i / (out_frames - 1) the
            # last frame sat on src_end, one frame past the video when the trim
            # runs to the end of the recording.
            t_ratio = i / out_frames
            source_t = src_start + t_ratio * src_duration
            
            frame = seek_and_read(source_t)
            if frame is None:
                problems.append(f"segment {seg_idx + 1} (play): no frame at source t={source_t:.2f}s; "
                                f"wrote {written} of {out_frames} frames")
                break
            
            resized = crop_and_resize(frame, source_t, in_w, in_h)
            if not write_frame(resized.tobytes()):
                problems.append(f"segment {seg_idx + 1} (play): the encoder stopped")
                break
            written += 1
    
    elif seg["type"] == "hold_narrate":
        source_t = seg["source_time"]
        hold_duration = seg["hold_duration"]
        hold_frames_count = int(hold_duration * FPS)
        
        # Read the single frame to hold on
        frame = seek_and_read(source_t)
        if frame is None:
            problems.append(f"segment {seg_idx + 1}: hold at source t={source_t:.2f}s skipped, "
                            f"the frame could not be read ({hold_duration:.1f}s missing)")
            continue
        
        resized = crop_and_resize(frame, source_t, in_w, in_h)
        frame_bytes = resized.tobytes()
        
        # Write the same frame repeatedly
        for _ in range(hold_frames_count):
            if not write_frame(frame_bytes):
                problems.append(f"segment {seg_idx + 1} (hold): the encoder stopped")
                break
        else:
            holds_rendered += 1

print(f"\n  Encoding complete: {output_frame_count} frames ({output_frame_count/FPS:.1f}s)", file=sys.stderr)
print(f"  Holds: {holds_rendered} of {holds_planned} rendered", file=sys.stderr)

encoder.stdin.close()
encoder.wait()
cap.release()

if encoder.returncode != 0:
    print(f"Error: ffmpeg exited {encoder.returncode}", file=sys.stderr)
    sys.exit(1)

print(f"  Video saved: {OUTPUT_VIDEO}", file=sys.stderr)
if problems:
    print(f"Error: the video is shorter than the timeline ({output_frame_count} of {total_est_frames} frames),"
          " so the narration will drift:", file=sys.stderr)
    for line in problems:
        print(f"  - {line}", file=sys.stderr)
    sys.exit(1)
