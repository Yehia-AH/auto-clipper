"""Find new uploads on the watched sources and download them with yt-dlp."""
import json
import os
import tempfile
from pathlib import Path

import yt_dlp

from .config import ROOT

STATE_FILE = ROOT / "state" / "processed.json"


def _base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True}
    # YouTube often blocks cloud IPs. Exporting your browser cookies into the
    # YTDLP_COOKIES secret (Netscape cookies.txt format) gets around that.
    cookies = os.environ.get("YTDLP_COOKIES")
    if cookies:
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        f.write(cookies)
        f.close()
        opts["cookiefile"] = f.name
    return opts


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def list_new_videos(cfg: dict, state: dict) -> list[dict]:
    """Return [{id, url, title}] for unprocessed uploads across all sources."""
    found = []
    opts = {**_base_opts(), "extract_flat": "in_playlist",
            "playlistend": cfg["lookback_videos"]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for src in cfg["sources"]:
            try:
                info = ydl.extract_info(src, download=False)
            except Exception as e:  # one bad source shouldn't stop the run
                print(f"[fetch] could not read {src}: {e}")
                continue
            entries = info.get("entries") or [info]
            for e in entries[: cfg["lookback_videos"]]:
                vid = e.get("id")
                if not vid or vid in state["processed"]:
                    continue
                dur = e.get("duration")
                if dur and dur < cfg["min_source_minutes"] * 60:
                    continue
                if e.get("live_status") in ("is_live", "is_upcoming"):
                    continue
                url = e.get("url") or e.get("webpage_url") or vid
                if not str(url).startswith("http"):
                    url = f"https://www.youtube.com/watch?v={vid}"
                found.append({"id": vid, "url": url, "title": e.get("title") or vid})
    return found


def download(url: str, workdir: Path) -> dict:
    """Download a video (max 1080p) as mp4. Returns {id, title, path, duration}."""
    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_base_opts(),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    return {"id": info["id"], "title": info.get("title") or info["id"],
            "path": path, "duration": info.get("duration"),
            "url": info.get("webpage_url") or url}
