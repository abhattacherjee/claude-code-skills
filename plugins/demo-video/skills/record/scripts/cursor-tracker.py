#!/usr/bin/env python3
"""Track mouse cursor position, clicks, and active window bounds.

Captures:
- Cursor coordinates at specified FPS via macOS Quartz API
- Mouse click events via CGEventTap (requires Accessibility permission)
- Active (frontmost) window bounds for cropping to the application window

All data written to a single JSONL file with typed lines.
"""
import argparse
import json
import signal
import sys
import time
import threading


def get_display_info():
    """Get screen size in pixels and Retina scale factor."""
    from Quartz import (
        CGMainDisplayID,
        CGDisplayPixelsWide,
        CGDisplayPixelsHigh,
        CGDisplayBounds,
    )
    display_id = CGMainDisplayID()
    pixel_w = CGDisplayPixelsWide(display_id)
    pixel_h = CGDisplayPixelsHigh(display_id)
    bounds = CGDisplayBounds(display_id)
    scale = pixel_w / bounds.size.width
    return pixel_w, pixel_h, scale


def get_active_window_bounds(scale):
    """Get the frontmost application's main window bounds (in pixels)."""
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        from AppKit import NSWorkspace

        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        if not active_app:
            return None
        active_pid = active_app.processIdentifier()
        app_name = active_app.localizedName()

        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        if not windows:
            return None

        # Find the largest window belonging to the active app
        best = None
        best_area = 0
        for w in windows:
            if w.get("kCGWindowOwnerPID") == active_pid:
                b = w.get("kCGWindowBounds", {})
                area = b.get("Width", 0) * b.get("Height", 0)
                if area > best_area:
                    best_area = area
                    best = b
                    best_name = w.get("kCGWindowName", "")

        if best:
            return {
                "app": app_name,
                "x": round(best["X"] * scale),
                "y": round(best["Y"] * scale),
                "w": round(best["Width"] * scale),
                "h": round(best["Height"] * scale),
            }
    except Exception:
        pass
    return None


def start_click_monitor(click_events, scale, start_time_ref):
    """Run a CGEventTap in a background thread to capture mouse clicks."""
    try:
        from Quartz import (
            CGEventTapCreate,
            CGEventGetLocation,
            CGEventTapEnable,
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            kCGEventLeftMouseDown,
            kCGEventRightMouseDown,
            CGEventMaskBit,
        )
        from Quartz import CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopRun
        from Quartz import CFRunLoopGetCurrent, kCFRunLoopCommonModes

        def callback(proxy, event_type, event, refcon):
            pos = CGEventGetLocation(event)
            px = pos.x * scale
            py = pos.y * scale
            t = time.monotonic() - start_time_ref[0]
            button = "left" if event_type == kCGEventLeftMouseDown else "right"
            click_events.append({"t": round(t, 4), "x": round(px, 1), "y": round(py, 1), "click": button})
            return event

        mask = CGEventMaskBit(kCGEventLeftMouseDown) | CGEventMaskBit(kCGEventRightMouseDown)
        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly,
            mask, callback, None,
        )
        if tap is None:
            print("Warning: No click tracking (grant Accessibility permission to Terminal)", file=sys.stderr)
            return
        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(loop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        CFRunLoopRun()
    except Exception as e:
        print(f"Warning: Click tracking failed: {e}", file=sys.stderr)


def track_cursor(output_path, fps=30):
    """Track cursor, clicks, and window bounds."""
    from Quartz import CGEventGetLocation, CGEventCreate

    screen_w, screen_h, scale = get_display_info()

    running = True
    click_events = []
    start_time_ref = [0.0]

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    interval = 1.0 / fps

    with open(output_path, "w") as f:
        header = {
            "type": "header",
            "screen_w": screen_w,
            "screen_h": screen_h,
            "scale": scale,
            "fps": fps,
        }
        f.write(json.dumps(header) + "\n")

        start_time = time.monotonic()
        start_time_ref[0] = start_time
        count = 0
        last_click_idx = 0
        last_window_check = 0

        # Start click monitor
        click_thread = threading.Thread(
            target=start_click_monitor,
            args=(click_events, scale, start_time_ref),
            daemon=True,
        )
        click_thread.start()

        while running:
            loop_start = time.monotonic()
            t = loop_start - start_time

            event = CGEventCreate(None)
            if event:
                pos = CGEventGetLocation(event)
                px = pos.x * scale
                py = pos.y * scale
                f.write(json.dumps({"t": round(t, 4), "x": round(px, 1), "y": round(py, 1)}) + "\n")
                count += 1

            # Track active window bounds every 0.5s (not every frame — too expensive)
            if t - last_window_check >= 0.5:
                wb = get_active_window_bounds(scale)
                if wb:
                    wb["type"] = "window"
                    wb["t"] = round(t, 4)
                    f.write(json.dumps(wb) + "\n")
                last_window_check = t

            # Flush clicks
            while last_click_idx < len(click_events):
                f.write(json.dumps(click_events[last_click_idx]) + "\n")
                last_click_idx += 1

            if count % fps == 0:
                f.flush()

            elapsed = time.monotonic() - loop_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    print(f"Cursor tracker: {count} positions, {len(click_events)} clicks", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track cursor, clicks, and window bounds on macOS")
    parser.add_argument("-o", "--output", required=True, help="Output JSONL file path")
    parser.add_argument("-f", "--fps", type=int, default=30, help="Tracking rate (default: 30)")
    args = parser.parse_args()
    track_cursor(args.output, args.fps)
