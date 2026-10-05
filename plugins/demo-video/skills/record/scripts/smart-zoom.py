#!/usr/bin/env python3
"""Post-process screen recording with intelligent cursor-following zoom.

State-machine zoom modes:
  --mode focus (default): Zooms in when cursor dwells on a UI element, zooms out
                          when cursor moves to a new area. Ideal for UI demos.
  --mode click:           Zooms in on mouse click events (requires Accessibility permission).
  --mode velocity:        Legacy mode — zooms based on cursor speed.

The 'focus' mode uses a 4-state machine:
  WIDE → APPROACHING → FOCUSED → RETREATING → WIDE
  - WIDE: Full window view. Default state.
  - APPROACHING: Cursor still for >dwell_time seconds → slowly zooming in.
  - FOCUSED: Zoomed in on the element. Holds until cursor moves away.
  - RETREATING: Cursor jumped away (navigation/scroll) → smoothly zooming out.
"""
import argparse
import json
import math
import subprocess
import sys
from collections import deque
from enum import Enum

try:
    import cv2
    import numpy as np
except ImportError:
    print("Missing dependencies: pip3 install opencv-python numpy", file=sys.stderr)
    sys.exit(1)


class ZoomState(Enum):
    WIDE = "wide"
    APPROACHING = "approaching"
    FOCUSED = "focused"
    RETREATING = "retreating"


def load_cursor_log(path):
    """Load cursor positions and click events from JSONL file."""
    header = None
    positions = []
    clicks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("type") == "header":
                header = data
            elif "click" in data:
                clicks.append(data)
            else:
                positions.append(data)
    return header, positions, clicks


def interpolate_position(positions, t):
    """Get cursor position at time t via linear interpolation."""
    if not positions:
        return 0.0, 0.0
    if t <= positions[0]["t"]:
        return positions[0]["x"], positions[0]["y"]
    if t >= positions[-1]["t"]:
        return positions[-1]["x"], positions[-1]["y"]

    lo, hi = 0, len(positions) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if positions[mid]["t"] <= t:
            lo = mid
        else:
            hi = mid

    p0, p1 = positions[lo], positions[hi]
    dt = p1["t"] - p0["t"]
    if dt == 0:
        return p0["x"], p0["y"]

    alpha = (t - p0["t"]) / dt
    x = p0["x"] + alpha * (p1["x"] - p0["x"])
    y = p0["y"] + alpha * (p1["y"] - p0["y"])
    return x, y


def find_active_click(clicks, t, hold_duration, zoom_in_time, zoom_out_time):
    """Find if time t falls within any click's zoom window (for click mode)."""
    total_window = zoom_in_time + hold_duration + zoom_out_time
    for click in clicks:
        ct = click["t"]
        if ct <= t < ct + total_window:
            elapsed = t - ct
            if elapsed < zoom_in_time:
                progress = smooth_step(elapsed / zoom_in_time)
            elif elapsed < zoom_in_time + hold_duration:
                progress = 1.0
            else:
                out_elapsed = elapsed - zoom_in_time - hold_duration
                progress = 1.0 - smooth_step(out_elapsed / zoom_out_time)
            return progress, click["x"], click["y"]
    return None


def smooth_step(t):
    """Ease-in-out: 3t^2 - 2t^3"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def process_video(input_path, cursor_path, output_path, config):
    """Process video with intelligent cursor-following zoom."""
    header, positions, clicks = load_cursor_log(cursor_path)
    if not header:
        print("Error: cursor log missing header line", file=sys.stderr)
        sys.exit(1)

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error: cannot open {input_path}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    in_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    in_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_w, out_h = config["output_res"]
    mode = config["mode"]

    print(f"  Input:  {in_w}x{in_h} @ {fps:.1f}fps, {total_frames} frames", file=sys.stderr)
    print(f"  Output: {out_w}x{out_h}, zoom {config['zoom_min']:.1f}x-{config['zoom_max']:.1f}x", file=sys.stderr)
    print(f"  Mode:   {mode}", file=sys.stderr)
    print(f"  Cursor: {len(positions)} positions, {len(clicks)} clicks", file=sys.stderr)

    if mode == "click" and len(clicks) == 0:
        print("  Warning: no clicks found — falling back to focus mode", file=sys.stderr)
        mode = "focus"

    # State machine state (for focus mode)
    state = ZoomState.WIDE
    still_start = 0.0          # when cursor became still
    focus_anchor_x = in_w / 2  # where we're zooming into
    focus_anchor_y = in_h / 2
    last_move_time = 0.0       # last time cursor moved significantly

    # Smoothed values
    current_zoom = config["zoom_min"]
    current_x = in_w / 2.0
    current_y = in_h / 2.0
    prev_cx, prev_cy = current_x, current_y

    # Velocity tracking (for velocity mode fallback)
    velocity_history = deque(maxlen=max(1, int(fps * 0.5)))

    # Position history for detecting stillness (focus mode)
    STILL_RADIUS = config.get("still_radius", 30)  # pixels — cursor within this = "still"

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
    target_zoom = config["zoom_min"]

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t = frame_idx / fps

        # Get cursor position
        cx, cy = interpolate_position(positions, t)
        cx = max(0.0, min(cx, float(in_w)))
        cy = max(0.0, min(cy, float(in_h)))

        # Calculate displacement from previous frame
        dx = cx - prev_cx
        dy = cy - prev_cy
        displacement = math.sqrt(dx * dx + dy * dy)

        if mode == "focus":
            # ── FOCUS MODE: State machine ──

            # Is cursor currently still? (within STILL_RADIUS of where it stopped)
            if state == ZoomState.WIDE:
                if displacement < STILL_RADIUS / fps * 2:
                    # Cursor barely moved
                    if frame_idx == 0:
                        still_start = t
                    still_duration = t - still_start
                    if still_duration >= config["dwell_time"]:
                        # Cursor has been still long enough → start approaching
                        state = ZoomState.APPROACHING
                        focus_anchor_x = cx
                        focus_anchor_y = cy
                else:
                    # Cursor moved — reset stillness timer
                    still_start = t

            elif state == ZoomState.APPROACHING:
                # Check if cursor moved away (abort zoom-in)
                dist_from_anchor = math.sqrt(
                    (cx - focus_anchor_x) ** 2 + (cy - focus_anchor_y) ** 2
                )
                if dist_from_anchor > config["move_away_threshold"]:
                    # Cursor left the area — abort, zoom back out
                    state = ZoomState.RETREATING
                    last_move_time = t
                elif current_zoom >= config["zoom_max"] * 0.95:
                    # Reached target zoom → focused
                    state = ZoomState.FOCUSED
                    still_start = t  # reset for focus hold tracking

                target_zoom = config["zoom_max"]

            elif state == ZoomState.FOCUSED:
                # Stay focused while cursor is near the anchor
                dist_from_anchor = math.sqrt(
                    (cx - focus_anchor_x) ** 2 + (cy - focus_anchor_y) ** 2
                )
                if dist_from_anchor > config["move_away_threshold"]:
                    # Cursor moved away significantly → retreat
                    state = ZoomState.RETREATING
                    last_move_time = t

                target_zoom = config["zoom_max"]
                # Gently follow small cursor movements within the focused area
                focus_anchor_x += (cx - focus_anchor_x) * 0.02
                focus_anchor_y += (cy - focus_anchor_y) * 0.02

            elif state == ZoomState.RETREATING:
                target_zoom = config["zoom_min"]
                if current_zoom <= config["zoom_min"] * 1.05:
                    # Fully zoomed out → back to wide
                    state = ZoomState.WIDE
                    still_start = t

            # Set target zoom for WIDE state
            if state == ZoomState.WIDE:
                target_zoom = config["zoom_min"]

            # Determine smoothing speed based on state
            if state == ZoomState.APPROACHING:
                zoom_speed = config["zoom_in_speed"]
                pos_speed = config["position_smooth"]
            elif state == ZoomState.RETREATING:
                zoom_speed = config["zoom_out_speed"]
                pos_speed = config["position_smooth"] * 0.5  # slower pan during retreat
            elif state == ZoomState.FOCUSED:
                zoom_speed = 0.02  # very gentle adjustments while focused
                pos_speed = 0.02
            else:  # WIDE
                zoom_speed = config["zoom_out_speed"]
                pos_speed = config["position_smooth"] * 0.3

            # Smooth zoom transition
            current_zoom += (target_zoom - current_zoom) * zoom_speed
            current_zoom = max(config["zoom_min"], min(config["zoom_max"], current_zoom))

            # Position target depends on state
            if state in (ZoomState.APPROACHING, ZoomState.FOCUSED):
                # Follow the focus anchor (where cursor paused)
                target_x = focus_anchor_x
                target_y = focus_anchor_y
            elif state == ZoomState.RETREATING:
                # Pan toward cursor's new position as we zoom out
                target_x = cx
                target_y = cy
            else:
                # WIDE: center of screen
                target_x = in_w / 2.0
                target_y = in_h / 2.0

            current_x += (target_x - current_x) * pos_speed
            current_y += (target_y - current_y) * pos_speed

        elif mode == "click":
            # ── CLICK MODE ──
            click_result = find_active_click(
                clicks, t,
                config["hold_duration"],
                config["click_zoom_in_time"],
                config["click_zoom_out_time"],
            )
            if click_result:
                factor, click_x, click_y = click_result
                target_zoom = config["zoom_min"] + factor * (config["zoom_max"] - config["zoom_min"])
                target_x = click_x
                target_y = click_y
            else:
                target_zoom = config["zoom_min"]
                target_x = in_w / 2.0
                target_y = in_h / 2.0

            current_zoom += (target_zoom - current_zoom) * 0.06
            current_zoom = max(config["zoom_min"], min(config["zoom_max"], current_zoom))
            current_x += (target_x - current_x) * 0.1
            current_y += (target_y - current_y) * 0.1

        else:
            # ── VELOCITY MODE (legacy) ──
            if frame_idx > 0:
                dt = 1.0 / fps
                velocity = displacement / dt
                velocity_history.append(velocity)

            avg_velocity = sum(velocity_history) / max(len(velocity_history), 1)
            dwell = config.get("dwell_threshold", 200)
            move = config.get("move_threshold", 800)

            if avg_velocity < dwell:
                target_zoom = config["zoom_max"]
            elif avg_velocity > move:
                target_zoom = config["zoom_min"]
            else:
                t_factor = (avg_velocity - dwell) / (move - dwell)
                target_zoom = config["zoom_max"] - t_factor * (config["zoom_max"] - config["zoom_min"])

            current_zoom += (target_zoom - current_zoom) * 0.03
            current_zoom = max(config["zoom_min"], min(config["zoom_max"], current_zoom))
            current_x += (cx - current_x) * 0.08
            current_y += (cy - current_y) * 0.08

        # Calculate crop window
        crop_w = int(in_w / current_zoom)
        crop_h = int(in_h / current_zoom)
        crop_w = crop_w - (crop_w % 2)
        crop_h = crop_h - (crop_h % 2)
        crop_w = max(crop_w, 2)
        crop_h = max(crop_h, 2)

        crop_x = int(current_x - crop_w / 2)
        crop_y = int(current_y - crop_h / 2)
        crop_x = max(0, min(crop_x, in_w - crop_w))
        crop_y = max(0, min(crop_y, in_h - crop_h))

        # Crop and resize
        cropped = frame[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
        if cropped.size == 0:
            cropped = frame
        resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

        try:
            encoder.stdin.write(resized.tobytes())
        except BrokenPipeError:
            print("\nEncoder pipe broken", file=sys.stderr)
            break

        if frame_idx % max(1, int(fps)) == 0:
            pct = (frame_idx / total_frames * 100) if total_frames > 0 else 0
            st = state.value if mode == "focus" else mode
            print(
                f"\r  Processing: {pct:5.1f}%  frame {frame_idx}/{total_frames}  "
                f"zoom {current_zoom:.1f}x  state={st}    ",
                end="",
                file=sys.stderr,
            )

        prev_cx, prev_cy = cx, cy
        frame_idx += 1

    encoder.stdin.close()
    encoder.wait()
    cap.release()

    if encoder.returncode != 0:
        print(f"\nError: ffmpeg exited with code {encoder.returncode}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Done: {output_path} ({frame_idx} frames)", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Post-process screen recording with intelligent cursor-following zoom",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MODES:
  focus     (default) State-machine zoom: dwell to zoom in, move away to zoom out.
            Shows full window by default, zooms in only on deliberate cursor pauses.
  click     Zoom on mouse click events (needs Accessibility permission).
  velocity  Legacy: continuous velocity-based zoom (jittery for UI demos).

EXAMPLES:
  # Focus mode — zoom into UI elements you pause on
  %(prog)s recording-raw.mp4 cursor.jsonl -o zoomed.mp4

  # Slower zoom-in, longer dwell threshold
  %(prog)s recording-raw.mp4 cursor.jsonl -o zoomed.mp4 --dwell-time 1.2 --zoom-in-speed 0.02

  # Higher zoom for small UI elements
  %(prog)s recording-raw.mp4 cursor.jsonl -o zoomed.mp4 --zoom-max 4.0

  # Click mode
  %(prog)s recording-raw.mp4 cursor.jsonl -o zoomed.mp4 --mode click --hold 2.0
        """,
    )
    parser.add_argument("input", help="Input video file")
    parser.add_argument("cursor_log", help="Cursor position JSONL file")
    parser.add_argument("-o", "--output", required=True, help="Output video file")
    parser.add_argument(
        "--mode", choices=["focus", "click", "velocity"], default="focus",
        help="Zoom mode (default: focus)",
    )
    parser.add_argument("--zoom-min", type=float, default=1.0, help="Min zoom, 1.0=full screen (default: 1.0)")
    parser.add_argument("--zoom-max", type=float, default=3.0, help="Max zoom level (default: 3.0)")
    parser.add_argument("--resolution", default="1920x1080", help="Output resolution WxH (default: 1920x1080)")

    # Focus mode
    focus = parser.add_argument_group("focus mode options")
    focus.add_argument("--dwell-time", type=float, default=0.8, help="Seconds cursor must be still before zoom starts (default: 0.8)")
    focus.add_argument("--move-away", type=float, default=200, help="Pixels cursor must move to trigger zoom-out (default: 200)")
    focus.add_argument("--still-radius", type=float, default=30, help="Pixel radius considered 'still' (default: 30)")
    focus.add_argument("--zoom-in-speed", type=float, default=0.03, help="Zoom-in smoothing, 0-1 (default: 0.03, slow and cinematic)")
    focus.add_argument("--zoom-out-speed", type=float, default=0.04, help="Zoom-out smoothing (default: 0.04)")
    focus.add_argument("--position-smooth", type=float, default=0.06, help="Pan smoothing (default: 0.06)")

    # Click mode
    click = parser.add_argument_group("click mode options")
    click.add_argument("--hold", type=float, default=1.5, help="Hold at max zoom after click (default: 1.5s)")
    click.add_argument("--click-zoom-in", type=float, default=0.3, help="Zoom-in time after click (default: 0.3s)")
    click.add_argument("--click-zoom-out", type=float, default=0.5, help="Zoom-out time after hold (default: 0.5s)")

    # Velocity mode (legacy)
    vel = parser.add_argument_group("velocity mode options (legacy)")
    vel.add_argument("--dwell-threshold", type=float, default=200, help="Speed threshold to zoom in (default: 200 px/s)")
    vel.add_argument("--move-threshold", type=float, default=800, help="Speed threshold to zoom out (default: 800 px/s)")

    args = parser.parse_args()
    out_w, out_h = map(int, args.resolution.split("x"))

    config = {
        "mode": args.mode,
        "zoom_min": args.zoom_min,
        "zoom_max": args.zoom_max,
        "output_res": (out_w, out_h),
        # Focus mode
        "dwell_time": args.dwell_time,
        "move_away_threshold": args.move_away,
        "still_radius": args.still_radius,
        "zoom_in_speed": args.zoom_in_speed,
        "zoom_out_speed": args.zoom_out_speed,
        "position_smooth": args.position_smooth,
        # Click mode
        "hold_duration": args.hold,
        "click_zoom_in_time": args.click_zoom_in,
        "click_zoom_out_time": args.click_zoom_out,
        # Velocity mode
        "dwell_threshold": args.dwell_threshold,
        "move_threshold": args.move_threshold,
    }

    process_video(args.input, args.cursor_log, args.output, config)
