# 🌍 Wanderlust — Travel Background Video App

A local web app that plays immersive travel videos as full-screen backgrounds,
fetched live from YouTube based on your destination search.

## Quick Start

### 1. Install Python dependencies

```bash
cd travel_bg
pip install -r requirements.txt
```

> **yt-dlp** handles YouTube search & download.  
> **ffmpeg** is needed for video merging (audio+video streams):

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (via choco)
choco install ffmpeg
```

### 2. (Optional) Add your default background

Place any `.mp4` file at:
```
/Users/arkadipbasu/Downloads/travel_bg_cache/europe_random.mp4
```
This plays automatically on every page load.

### 3. Run the app

```bash
python app.py
```

Open **http://localhost:5001** in your browser.

---

## Features

| Feature | How it works |
|---|---|
| **Destination search** | Type a place → yt-dlp searches YouTube → downloads best travel video → plays as background |
| **Download caching** | Videos cached in `~/Downloads/travel_bg_cache/` — same place loads instantly on repeat visits |
| **Custom video path** | Enter a local path (`~/Downloads/clip.mp4`) or any online `.mp4` URL |
| **Default background** | `~/Downloads/travel_bg_cache/europe_random.mp4` auto-loads on startup |
| **Quick tags** | Click Santorini, Kyoto, etc. for one-tap searches |
| **Range streaming** | Efficient HTTP range requests — no full-file buffering |

## Folder structure

```
travel_bg/
├── app.py              # Flask backend
├── requirements.txt
├── templates/
│   └── index.html      # Full UI
└── README.md
```

Cache dir: `~/Downloads/travel_bg_cache/`

## Notes

- First search for a new place takes **20–60 seconds** (download time). A spinner shows progress.
- Videos are capped at 720p and 10 minutes for reasonable file sizes.
- The app runs entirely **offline-capable** once videos are cached.
- To update yt-dlp (YouTube sometimes breaks it): `pip install -U yt-dlp`
