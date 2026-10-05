#!/usr/bin/env python3
"""Generate an HTML preview of the integrated timeline.

Extracts a screenshot for each HOLD frame, pairs it with its TTS audio,
and serves a local HTML page where the user can review narration-visual
alignment before committing to the full render (which takes 5+ minutes).

Usage:
  python3 preview-timeline.py <raw-video> <zoom-script> <timeline> <tts-dir> [-o output-dir]
  python3 preview-timeline.py --help

The preview opens in the default browser at http://localhost:8111
"""
import argparse
import json
import os
import subprocess
import sys
import http.server
import threading
import webbrowser
from pathlib import Path

try:
    import cv2
except ImportError:
    print("Missing: pip3 install opencv-python", file=sys.stderr)
    sys.exit(1)


def extract_preview_frames(video_path, zoom_script, timeline, output_dir):
    """Extract a screenshot for each HOLD segment in the timeline."""
    trim_start = zoom_script["trim"]["start"]
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30

    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    frame_paths = []
    for i, seg in enumerate(timeline):
        if seg["type"] == "hold_narrate":
            abs_time = trim_start + seg["source_time"]
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(abs_time * fps))
            ret, frame = cap.read()
            if not ret:
                frame_paths.append(None)
                continue
            h, w = frame.shape[:2]
            preview_w = 1920
            preview_h = int(h * preview_w / w)
            resized = cv2.resize(frame, (preview_w, preview_h))
            path = os.path.join(frames_dir, f"hold_{i:02d}.jpg")
            cv2.imwrite(path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
            frame_paths.append(f"frames/hold_{i:02d}.jpg")
        elif seg["type"] == "play":
            # Also extract frame for play segments (from midpoint)
            mid_source = (seg["source_start"] + seg["source_end"]) / 2
            abs_time = trim_start + mid_source
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(abs_time * fps))
            ret, frame = cap.read()
            if not ret:
                frame_paths.append(None)
                continue
            h, w = frame.shape[:2]
            preview_w = 1920
            preview_h = int(h * preview_w / w)
            resized = cv2.resize(frame, (preview_w, preview_h))
            path = os.path.join(frames_dir, f"play_{i:02d}.jpg")
            cv2.imwrite(path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
            frame_paths.append(f"frames/play_{i:02d}.jpg")
        else:
            frame_paths.append(None)

    cap.release()
    return frame_paths


def generate_html(timeline, tts_placement, frame_paths, tts_dir, output_dir):
    """Generate an HTML preview page."""

    # Load TTS manifest for transcribed text
    tts_text_map = {}  # filename -> text
    manifest_path = os.path.join(tts_dir, "tts-manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            for entry in json.load(f):
                fname = os.path.basename(entry.get("file", ""))
                tts_text_map[fname] = entry.get("text", "")

    # Build segment data for the HTML
    segments = []
    cumulative_time = 0.0

    # Track which TTS placements have been assigned to avoid double-counting
    assigned_placements = set()

    for i, seg in enumerate(timeline):
        if seg["type"] == "play":
            # Find TTS files that fall during this play segment
            play_tts = []
            for pi, placement in enumerate(tts_placement):
                if pi in assigned_placements:
                    continue
                if cumulative_time - 0.5 <= placement["output_time"] < cumulative_time + seg["duration"] + 0.5:
                    tts_file = os.path.basename(placement["file"])
                    play_tts.append({
                        "file": f"tts/{tts_file}",
                        "offset": placement["output_time"] - cumulative_time,
                        "duration": placement["duration"],
                        "text": tts_text_map.get(tts_file, ""),
                    })
                    assigned_placements.add(pi)
            segments.append({
                "type": "play",
                "duration": seg["duration"],
                "source_range": f"{seg['source_start']:.1f}s \u2192 {seg['source_end']:.1f}s",
                "output_time": cumulative_time,
                "frame": frame_paths[i] if frame_paths[i] else None,
                "tts": play_tts,
                "description": seg.get("description", ""),
            })
            cumulative_time += seg["duration"]
        elif seg["type"] == "hold_narrate":
            # Find TTS files for this hold
            hold_tts = []
            for pi, placement in enumerate(tts_placement):
                if pi in assigned_placements:
                    continue
                if cumulative_time - 0.5 <= placement["output_time"] < cumulative_time + seg["hold_duration"] + 0.5:
                    tts_file = os.path.basename(placement["file"])
                    hold_tts.append({
                        "file": f"tts/{tts_file}",
                        "offset": placement["output_time"] - cumulative_time,
                        "duration": placement["duration"],
                        "text": tts_text_map.get(tts_file, ""),
                    })
                    assigned_placements.add(pi)

            segments.append({
                "type": "hold",
                "duration": seg["hold_duration"],
                "source_time": seg["source_time"],
                "frame": frame_paths[i],
                "tts": hold_tts,
                "output_time": cumulative_time,
                "seg_ids": seg.get("segments", []),
                "description": seg.get("description", ""),
            })
            cumulative_time += seg["hold_duration"]

    # Copy TTS files to preview dir
    tts_preview_dir = os.path.join(output_dir, "tts")
    os.makedirs(tts_preview_dir, exist_ok=True)
    import shutil
    for f in os.listdir(tts_dir):
        if f.endswith(".mp3"):
            src = os.path.join(tts_dir, f)
            dst = os.path.join(tts_preview_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)

    total_duration = cumulative_time

    # Format time as M:SS
    def fmt_time(t):
        m = int(t) // 60
        s = int(t) % 60
        return f"{m}:{s:02d}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Demo Preview \u2014 Timeline Review</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; }}
  .header {{ background: #16213e; padding: 20px 30px; border-bottom: 2px solid #0f3460; }}
  .header h1 {{ font-size: 24px; color: #e94560; }}
  .header p {{ color: #888; margin-top: 5px; }}
  .timeline {{ max-width: 1400px; margin: 30px auto; padding: 0 20px; }}
  .segment {{ margin-bottom: 24px; border-radius: 12px; overflow: hidden; }}
  .play-segment {{ background: #16213e; padding: 12px 20px; border-left: 4px solid #0f3460; }}
  .play-segment .label {{ color: #0f3460; font-weight: 600; font-size: 13px; text-transform: uppercase; }}
  .play-segment .desc {{ color: #666; font-size: 12px; margin-top: 2px; }}
  .hold-segment {{ background: #1a1a2e; border: 1px solid #333; }}
  .hold-header {{ background: #16213e; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
  .hold-header .label {{ color: #e94560; font-weight: 600; font-size: 13px; text-transform: uppercase; }}
  .hold-header .time {{ color: #888; font-size: 13px; font-family: monospace; }}
  .hold-header .desc {{ width: 100%; color: #999; font-size: 12px; font-style: italic; }}
  .hold-frame {{ padding: 12px 20px 0; }}
  .hold-frame img {{ width: 100%; border-radius: 8px; border: 1px solid #333; }}
  .hold-narration {{ padding: 12px 20px; display: flex; flex-wrap: wrap; gap: 10px; }}
  .tts-item {{ background: #16213e; padding: 12px 16px; border-radius: 8px; flex: 1 1 280px; min-width: 250px; }}
  .tts-row {{ display: flex; align-items: flex-start; gap: 12px; }}
  .audio-num {{ color: #e94560; font-weight: 700; font-size: 14px; font-family: monospace; min-width: 28px; text-align: right; flex-shrink: 0; margin-top: 4px; }}
  .tts-item .play-btn {{ background: #e94560; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; white-space: nowrap; min-width: 70px; text-align: center; flex-shrink: 0; margin-top: 2px; }}
  .tts-item .play-btn:hover {{ background: #c73a52; }}
  .tts-item .play-btn.paused {{ background: #ff6b35; }}
  .tts-text {{ font-size: 14px; line-height: 1.5; color: #e0e0e0; }}
  .tts-meta {{ color: #666; font-size: 11px; margin-top: 4px; }}
  .progress-bar {{ width: 100%; height: 4px; background: #333; border-radius: 2px; margin-top: 8px; overflow: hidden; display: none; }}
  .progress-bar.active {{ display: block; }}
  .progress-fill {{ height: 100%; background: #e94560; border-radius: 2px; width: 0%; transition: width 0.1s linear; }}
  .section-feedback {{ padding: 8px 20px 15px; }}
  .section-feedback textarea {{ width: 100%; height: 40px; background: #0d1b2a; border: 1px solid #333; color: #e0e0e0; padding: 8px 12px; border-radius: 6px; font-size: 13px; resize: vertical; }}
  .section-feedback textarea::placeholder {{ color: #555; }}
  .section-feedback textarea:not(:placeholder-shown) {{ border-color: #e94560; }}
  .save-bar {{ max-width: 1400px; margin: 30px auto; padding: 20px; background: #16213e; border-radius: 12px; display: flex; align-items: center; gap: 16px; }}
  .save-btn {{ background: #27ae60; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: 600; }}
  .save-btn:hover {{ background: #219a52; }}
  .save-status {{ color: #888; font-size: 14px; }}
  .stats {{ display: flex; gap: 20px; margin-top: 10px; flex-wrap: wrap; }}
  .stat {{ background: #0f3460; padding: 8px 16px; border-radius: 6px; font-size: 13px; }}
  .playall-btn {{ background: #e94560; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 16px; margin: 20px 0; }}
  .playall-btn:hover {{ background: #c73a52; }}
  .now-playing-bar {{ position: sticky; top: 0; z-index: 100; background: #0d1b2a; border-bottom: 2px solid #e94560; padding: 12px 30px; display: none; align-items: center; gap: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
  .now-playing-bar.active {{ display: flex; }}
  .now-playing-bar .np-indicator {{ background: #e94560; color: white; padding: 4px 12px; border-radius: 4px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; animation: pulse 1.5s ease-in-out infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} }}
  .now-playing-bar .np-text {{ flex: 1; font-size: 14px; color: #ccc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .now-playing-bar .np-time {{ color: #888; font-size: 13px; font-family: monospace; }}
  .hold-segment.playing {{ border-color: #e94560; box-shadow: 0 0 15px rgba(233,69,96,0.3); }}
  .hold-segment.playing .hold-header {{ background: #2a1525; }}
  .tts-item.playing {{ background: #2a1525; border-left: 3px solid #e94560; }}
</style>
</head>
<body>
<div class="now-playing-bar" id="nowPlayingBar">
  <span class="np-indicator">NOW PLAYING</span>
  <span class="np-text" id="npText">\u2014</span>
  <span class="np-time" id="npTime">0:00</span>
</div>

<div class="header">
  <h1>Demo Preview \u2014 Timeline Review</h1>
  <p>Review narration-visual alignment before rendering. Click Play to hear each segment. Spacebar pauses globally.</p>
  <div class="stats">
    <div class="stat">Total: {fmt_time(total_duration)} ({total_duration:.1f}s)</div>
    <div class="stat">Segments: {len(timeline)}</div>
    <div class="stat">Holds: {sum(1 for s in segments if s['type']=='hold')}</div>
    <div class="stat">TTS: {len(tts_placement)} clips</div>
  </div>
  <button class="playall-btn" id="playAllBtn" onclick="playAll()">Play All (Sequential)</button>
</div>

<div class="timeline" id="timeline">
"""

    section_idx = 0  # Track hold/play-with-tts sections for feedback indexing
    audio_num = 1  # Global audio segment numbering
    for i, seg in enumerate(segments):
        if seg["type"] == "play":
            if seg.get("tts"):
                # Play segment WITH narration — show as a full section
                html += f"""
  <div class="segment hold-segment" id="seg-{section_idx}">
    <div class="hold-header">
      <span class="label" style="color:#0f3460">PLAY \u2014 {seg['duration']:.1f}s (source {seg['source_range']})</span>
      <span class="time">{fmt_time(seg['output_time'])} \u2192 {fmt_time(seg['output_time'] + seg['duration'])}</span>
"""
                if seg.get("description"):
                    html += f'      <span class="desc">{seg["description"]}</span>\n'
                html += '    </div>\n'
                if seg.get("frame"):
                    html += f'    <div class="hold-frame"><img src="{seg["frame"]}" alt="Play frame"></div>\n'
                html += '    <div class="hold-narration">\n'
                for j, tts in enumerate(seg.get("tts", [])):
                    text = tts.get("text", "") or "\u2014"
                    html += f"""      <div class="tts-item" id="tts-{section_idx}-{j}">
        <div class="tts-row">
          <span class="audio-num">#{audio_num}</span>
          <button class="play-btn" data-src="{tts["file"]}" onclick="toggleAudio(this)">Play</button>
          <div>
            <div class="tts-text">{text}</div>
            <div class="tts-meta">{tts['duration']:.1f}s</div>
          </div>
        </div>
        <div class="progress-bar"><div class="progress-fill"></div></div>
      </div>
"""
                    audio_num += 1
                html += '    </div>\n'
                html += f'    <div class="section-feedback"><textarea placeholder="Feedback for this section..."></textarea></div>\n'
                html += '  </div>\n'
                section_idx += 1
            else:
                # Play segment without TTS — show as thin bar with description
                desc = seg.get("description", "")
                html += f"""
  <div class="segment play-segment">
    <div class="label">PLAY \u2014 {seg['duration']:.1f}s (source {seg['source_range']})</div>
"""
                if desc:
                    html += f'    <div class="desc">{desc}</div>\n'
                html += '  </div>\n'
        elif seg["type"] == "hold":
            html += f"""
  <div class="segment hold-segment" id="seg-{section_idx}">
    <div class="hold-header">
      <span class="label">HOLD \u2014 {seg['duration']:.1f}s at source t={seg['source_time']:.1f}s</span>
      <span class="time">{fmt_time(seg['output_time'])} \u2192 {fmt_time(seg['output_time'] + seg['duration'])}</span>
"""
            if seg.get("description"):
                html += f'      <span class="desc">{seg["description"]}</span>\n'
            html += '    </div>\n'
            if seg.get("frame"):
                html += f'    <div class="hold-frame"><img src="{seg["frame"]}" alt="Frame at t={seg["source_time"]:.1f}s"></div>\n'

            html += '    <div class="hold-narration">\n'
            for j, tts in enumerate(seg.get("tts", [])):
                text = tts.get("text", "") or "\u2014"
                html += f"""      <div class="tts-item" id="tts-{section_idx}-{j}">
        <div class="tts-row">
          <span class="audio-num">#{audio_num}</span>
          <button class="play-btn" data-src="{tts["file"]}" onclick="toggleAudio(this)">Play</button>
          <div>
            <div class="tts-text">{text}</div>
            <div class="tts-meta">{tts['duration']:.1f}s</div>
          </div>
        </div>
        <div class="progress-bar"><div class="progress-fill"></div></div>
      </div>
"""
                audio_num += 1
            if not seg.get("tts"):
                html += '      <div class="tts-item"><div class="tts-text" style="color:#666">No narration (silent hold)</div></div>\n'
            html += '    </div>\n'
            html += f'    <div class="section-feedback"><textarea placeholder="Feedback for this section..."></textarea></div>\n'
            html += '  </div>\n'
            section_idx += 1

    html += """
</div>

<div class="save-bar">
  <button class="save-btn" onclick="saveFeedback()">Save Feedback</button>
  <span class="save-status" id="saveStatus">Feedback auto-saves to localStorage</span>
</div>

<script>
let currentAudio = null;
let isPlayingAll = false;
let playAllAbort = false;
let activeBtn = null;
let progressInterval = null;

function clearActive() {
  document.querySelectorAll('.hold-segment.playing').forEach(el => el.classList.remove('playing'));
  document.querySelectorAll('.tts-item.playing').forEach(el => el.classList.remove('playing'));
  document.querySelectorAll('.play-btn').forEach(el => { el.textContent = 'Play'; el.classList.remove('paused'); });
  document.querySelectorAll('.progress-bar').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.progress-fill').forEach(el => el.style.width = '0%');
  document.getElementById('nowPlayingBar').classList.remove('active');
  document.getElementById('npText').textContent = '—';
  document.getElementById('npTime').textContent = '0:00';
  if (progressInterval) { clearInterval(progressInterval); progressInterval = null; }
  activeBtn = null;
}

function setActive(btn) {
  const ttsItem = btn.closest('.tts-item');
  if (ttsItem) ttsItem.classList.add('playing');
  const seg = btn.closest('.hold-segment');
  if (seg) seg.classList.add('playing');
  const bar = document.getElementById('nowPlayingBar');
  bar.classList.add('active');
  const textEl = ttsItem?.querySelector('.text');
  document.getElementById('npText').textContent = textEl?.textContent || '...';
  activeBtn = btn;
}

function updateProgress() {
  if (!currentAudio || !activeBtn) return;
  const ttsItem = activeBtn.closest('.tts-item');
  const progressBar = ttsItem?.querySelector('.progress-bar');
  const progressFill = ttsItem?.querySelector('.progress-fill');
  if (progressBar && progressFill && currentAudio.duration) {
    progressBar.classList.add('active');
    const pct = (currentAudio.currentTime / currentAudio.duration) * 100;
    progressFill.style.width = pct + '%';
  }
  const cur = Math.floor(currentAudio.currentTime);
  const dur = Math.floor(currentAudio.duration) || 0;
  document.getElementById('npTime').textContent =
    Math.floor(cur/60) + ':' + String(cur%60).padStart(2,'0') + ' / ' +
    Math.floor(dur/60) + ':' + String(dur%60).padStart(2,'0');
}

function toggleAudio(btn) {
  const src = btn.dataset.src;
  if (!src) return;
  if (activeBtn === btn && currentAudio) {
    if (currentAudio.paused) {
      currentAudio.play();
      btn.textContent = 'Pause';
      btn.classList.remove('paused');
      progressInterval = setInterval(updateProgress, 100);
    } else {
      currentAudio.pause();
      btn.textContent = 'Resume';
      btn.classList.add('paused');
      if (progressInterval) { clearInterval(progressInterval); progressInterval = null; }
    }
    return;
  }
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  clearActive();
  setActive(btn);
  btn.textContent = 'Pause';
  currentAudio = new Audio(src);
  currentAudio.play();
  progressInterval = setInterval(updateProgress, 100);
  currentAudio.onended = () => { clearActive(); currentAudio = null; };
  currentAudio.onerror = () => { btn.textContent = 'Error'; clearActive(); };
}

function stopAll() {
  playAllAbort = true;
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  clearActive();
  isPlayingAll = false;
  document.getElementById('playAllBtn').textContent = 'Play All (Sequential)';
}

async function playAll() {
  if (isPlayingAll) { stopAll(); return; }
  isPlayingAll = true;
  playAllAbort = false;
  document.getElementById('playAllBtn').textContent = 'Stop';
  const btns = document.querySelectorAll('.tts-item .play-btn');
  for (const btn of btns) {
    if (playAllAbort) break;
    const src = btn.dataset.src;
    if (!src) continue;
    if (currentAudio) { currentAudio.pause(); }
    clearActive();
    setActive(btn);
    btn.textContent = 'Pause';
    btn.closest('.hold-segment')?.scrollIntoView({behavior:'smooth',block:'center'});
    await new Promise(resolve => {
      currentAudio = new Audio(src);
      currentAudio.play();
      progressInterval = setInterval(updateProgress, 100);
      currentAudio.onended = () => { clearActive(); currentAudio = null; resolve(); };
      currentAudio.onerror = () => { btn.textContent = 'Error'; resolve(); };
    });
    if (playAllAbort) break;
    await new Promise(r => setTimeout(r, 400));
  }
  isPlayingAll = false;
  clearActive();
  document.getElementById('playAllBtn').textContent = 'Play All (Sequential)';
}

document.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && e.target.tagName !== 'TEXTAREA') {
    e.preventDefault();
    if (currentAudio && activeBtn) toggleAudio(activeBtn);
    else if (!currentAudio) document.getElementById('playAllBtn').click();
  }
  if (e.code === 'Escape') stopAll();
});

function saveFeedback() {
  const sections = document.querySelectorAll('.section-feedback textarea');
  const holds = document.querySelectorAll('.hold-segment');
  const feedback = [];
  sections.forEach((ta, i) => {
    if (ta.value.trim()) {
      const hold = holds[i];
      const label = hold?.querySelector('.hold-header .label')?.textContent || 'Section ' + i;
      feedback.push({ section: i, label: label.trim(), feedback: ta.value.trim() });
    }
  });
  if (feedback.length === 0) {
    document.getElementById('saveStatus').textContent = 'No feedback to save (all fields empty)';
    return;
  }
  // POST to server so Claude can read it directly
  fetch('/feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(feedback, null, 2)
  }).then(r => {
    if (r.ok) {
      document.getElementById('saveStatus').textContent = 'Submitted ' + feedback.length + ' feedback notes to server';
      document.getElementById('saveStatus').style.color = '#27ae60';
    } else {
      throw new Error('Server error');
    }
  }).catch(() => {
    // Fallback to download
    const blob = new Blob([JSON.stringify(feedback, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'feedback.json';
    a.click();
    URL.revokeObjectURL(url);
    document.getElementById('saveStatus').textContent = 'Downloaded feedback.json (server unavailable)';
  });
  localStorage.setItem('demo-preview-feedback', JSON.stringify(feedback));
}

// Restore feedback from localStorage on page load
window.addEventListener('load', () => {
  try {
    const saved = JSON.parse(localStorage.getItem('demo-preview-feedback') || '[]');
    const sections = document.querySelectorAll('.section-feedback textarea');
    saved.forEach(item => {
      if (item.section < sections.length) {
        sections[item.section].value = item.feedback;
      }
    });
    if (saved.length > 0) {
      document.getElementById('saveStatus').textContent = 'Restored ' + saved.length + ' saved notes. Auto-saves to localStorage.';
    }
  } catch(e) {}
});

// Auto-save to localStorage on every textarea change
document.addEventListener('input', (e) => {
  if (e.target.matches('.section-feedback textarea')) {
    const sections = document.querySelectorAll('.section-feedback textarea');
    const feedback = [];
    sections.forEach((ta, i) => {
      if (ta.value.trim()) {
        const hold = document.querySelectorAll('.hold-segment')[i];
        const label = hold?.querySelector('.hold-header .label')?.textContent || 'Section ' + i;
        feedback.push({ section: i, label: label.trim(), feedback: ta.value.trim() });
      }
    });
    localStorage.setItem('demo-preview-feedback', JSON.stringify(feedback));
    document.getElementById('saveStatus').textContent = 'Auto-saved ' + feedback.length + ' notes';
  }
});
</script>
</body>
</html>"""
    html_path = os.path.join(output_dir, "preview.html")
    with open(html_path, "w") as f:
        f.write(html)

    return html_path


def serve_preview(output_dir, port=8111):
    """Start a local HTTP server with POST /feedback endpoint."""
    os.chdir(output_dir)
    feedback_path = os.path.join(output_dir, "feedback.json")

    class PreviewHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Suppress logs

        def do_POST(self):
            if self.path == "/feedback":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                with open(feedback_path, "wb") as f:
                    f.write(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                # Print to stderr so Claude can see it
                try:
                    data = json.loads(body)
                    print(f"\n  Feedback received: {len(data)} notes saved to {feedback_path}", file=sys.stderr)
                except Exception:
                    pass
            else:
                self.send_error(404)

    server = http.server.HTTPServer(("localhost", port), PreviewHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}/preview.html"
    print(f"\n  Preview server: {url}", file=sys.stderr)
    print(f"  Press Ctrl+C to stop\n", file=sys.stderr)
    webbrowser.open(url)

    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Preview demo timeline before rendering")
    parser.add_argument("video", help="Raw video file")
    parser.add_argument("zoom_script", help="Zoom script JSON")
    parser.add_argument("timeline", help="Integrated timeline JSON")
    parser.add_argument("tts_dir", help="Directory containing TTS .mp3 files")
    parser.add_argument("-o", "--output", default=None, help="Output directory for preview (default: <tts_dir>/../preview)")
    parser.add_argument("--port", type=int, default=8111, help="Server port (default: 8111)")
    parser.add_argument("--no-serve", action="store_true", help="Generate preview without starting server")
    args = parser.parse_args()

    output_dir = args.output or os.path.join(os.path.dirname(args.tts_dir), "preview")
    os.makedirs(output_dir, exist_ok=True)

    with open(args.zoom_script) as f:
        zoom_script = json.load(f)
    with open(args.timeline) as f:
        timeline_data = json.load(f)

    timeline = timeline_data["timeline"]
    tts_placement = timeline_data["tts_placement"]

    print("  Extracting preview frames...", file=sys.stderr)
    frame_paths = extract_preview_frames(args.video, zoom_script, timeline, output_dir)

    print("  Generating HTML preview...", file=sys.stderr)
    html_path = generate_html(timeline, tts_placement, frame_paths, args.tts_dir, output_dir)
    print(f"  Preview: {html_path}", file=sys.stderr)

    if not args.no_serve:
        serve_preview(output_dir, args.port)


if __name__ == "__main__":
    main()
