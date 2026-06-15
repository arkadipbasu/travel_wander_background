#!/usr/bin/env python3
"""
Travel Background Video App
- Flask backend
- yt-dlp for YouTube video search & download
- Serves local/online video as background
"""

import os
import re
import json
import glob
import hashlib
import threading
import subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))
CORS(app)

CACHE_DIR = Path(os.path.expanduser("~/Downloads/travel_bg_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VIDEO = os.path.expanduser("~/Downloads/travel_bg_cache/europe_random.mp4")

# ── helpers ──────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name).strip()[:80]


def cache_path(place: str) -> Path:
    key = hashlib.md5(place.lower().encode()).hexdigest()[:10]
    return CACHE_DIR / f"{sanitize(place)}_{key}.mp4"


def yt_dlp_available() -> bool:
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def download_video(place: str, dest: Path) -> dict:
    """Search YouTube and download best travel video via yt-dlp.

    Strategy:
    - Search top 5 results so we can skip blocked/too-long ones
    - No duration filter at search time (filter after via --match-filter)
    - Format fallback chain: mp4 preferred, but accept any and convert
    - Output to a known temp prefix so we can find the file reliably
    """
    query = f"{place} travel scenic 4k"
    tmp_prefix = CACHE_DIR / f"_tmp_{dest.stem}"

    # Clean up any leftover tmp files from a previous failed attempt
    for f in CACHE_DIR.glob(f"_tmp_{dest.stem}*"):
        f.unlink(missing_ok=True)

    cmd = [
        "yt-dlp",
        f"ytsearch5:{query}",        # try top 5 results, pick first that works
        "--format",
        # prefer mp4 video + any audio, fall back to best single-file
        "bestvideo[ext=mp4][height<=720]+bestaudio/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4",
        "--match-filter", "duration < 1800",  # skip anything over 30 min
        "--output", str(tmp_prefix) + ".%(ext)s",
        "--no-playlist",
        "--no-check-certificate",
        "--quiet",
        "--no-warnings",
        "--print", "after_move:filepath",   # prints final path to stdout
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    # First try: use the path yt-dlp printed to stdout
    printed_path = result.stdout.strip().splitlines()
    for p in printed_path:
        p = p.strip()
        if p and Path(p).exists():
            Path(p).rename(dest)
            return {"ok": True, "path": str(dest), "title": place}

    # Second try: glob for any file with our tmp prefix
    candidates = sorted(CACHE_DIR.glob(f"_tmp_{dest.stem}*"))
    # prefer .mp4, accept anything
    ordered = [c for c in candidates if c.suffix == ".mp4"] +               [c for c in candidates if c.suffix != ".mp4"]
    if ordered:
        ordered[0].rename(dest)
        # clean up remaining
        for c in candidates[1:]:
            c.unlink(missing_ok=True)
        return {"ok": True, "path": str(dest), "title": place}

    # Nothing found — surface the real yt-dlp error
    err = (result.stderr or "").strip()
    if not err:
        err = "No video file produced. Try a different place name."
    return {"ok": False, "error": err}


# ── background download state ─────────────────────────────────────────────

_download_state: dict = {}   # place_key -> {"status": ..., "title": ..., "error": ...}
_state_lock = threading.Lock()


def _bg_download(place: str, dest: Path):
    key = place.lower()
    with _state_lock:
        _download_state[key] = {"status": "downloading"}
    result = download_video(place, dest)
    with _state_lock:
        if result["ok"]:
            _download_state[key] = {"status": "done", "title": result.get("title", place)}
        else:
            _download_state[key] = {"status": "error", "error": result.get("error", "unknown")}


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def search():
    """Kick off video search/download for a place."""
    data = request.get_json(silent=True) or {}
    place = (data.get("place") or "").strip()
    if not place:
        return jsonify({"error": "No place provided"}), 400

    dest = cache_path(place)

    # already cached?
    if dest.exists() and dest.stat().st_size > 100_000:
        return jsonify({"status": "ready", "video_url": f"/video/cache/{dest.name}", "place": place})

    if not yt_dlp_available():
        return jsonify({"error": "yt-dlp not installed. Run: pip install yt-dlp"}), 503

    key = place.lower()
    with _state_lock:
        state = _download_state.get(key, {})

    if state.get("status") == "downloading":
        return jsonify({"status": "downloading", "place": place})

    if state.get("status") == "done" and dest.exists():
        return jsonify({"status": "ready", "video_url": f"/video/cache/{dest.name}", "place": place})

    # start background download
    t = threading.Thread(target=_bg_download, args=(place, dest), daemon=True)
    t.start()
    return jsonify({"status": "downloading", "place": place})


@app.route("/api/status/<place>")
def status(place):
    """Poll download status."""
    dest = cache_path(place)
    if dest.exists() and dest.stat().st_size > 100_000:
        return jsonify({"status": "ready", "video_url": f"/video/cache/{dest.name}"})

    key = place.lower()
    with _state_lock:
        state = _download_state.get(key, {})

    if not state:
        return jsonify({"status": "not_started"})
    return jsonify(state | ({"video_url": f"/video/cache/{dest.name}"} if state.get("status") == "done" else {}))


@app.route("/api/default_video")
def default_video_info():
    """Check default video availability."""
    if os.path.exists(DEFAULT_VIDEO):
        return jsonify({"available": True, "url": "/video/default"})
    return jsonify({"available": False})


@app.route("/video/default")
def serve_default():
    if not os.path.exists(DEFAULT_VIDEO):
        return "Default video not found", 404
    return _stream_video(DEFAULT_VIDEO)


@app.route("/video/cache/<filename>")
def serve_cache(filename):
    safe = Path(filename).name   # no path traversal
    path = CACHE_DIR / safe
    if not path.exists():
        return "Not found", 404
    return _stream_video(str(path))


@app.route("/video/custom", methods=["POST"])
def serve_custom():
    """Serve a local file path or proxy an online URL."""
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "No path"}), 400

    # online URL: just return it directly (browser will fetch)
    if path.startswith("http://") or path.startswith("https://"):
        return jsonify({"url": path, "type": "external"})

    # local path
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return jsonify({"error": f"File not found: {expanded}"}), 404

    # copy to cache so we can serve it
    dest = CACHE_DIR / f"custom_{Path(expanded).name}"
    if not dest.exists():
        import shutil
        shutil.copy2(expanded, dest)
    return jsonify({"url": f"/video/cache/{dest.name}", "type": "local"})


def _stream_video(path: str):
    """Range-aware video streaming."""
    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range")

    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else file_size - 1
            length = end - start + 1

            def generate():
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return Response(
                generate(),
                206,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                    "Content-Type": "video/mp4",
                },
            )

    return send_file(path, mimetype="video/mp4", conditional=True)


if __name__ == "__main__":
    print("🌍 Travel Background Video App")
    print(f"   Cache dir : {CACHE_DIR}")
    print(f"   Default   : {DEFAULT_VIDEO}")
    print(f"   yt-dlp    : {'✓ found' if yt_dlp_available() else '✗ missing — run: pip install yt-dlp'}")
    print("   Open      : http://localhost:5001\n")
    app.run(debug=True, host="0.0.0.0", port=5001)