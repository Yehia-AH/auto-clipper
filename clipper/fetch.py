"""Find new uploads on the watched sources and download them with yt-dlp."""
import json
import os
import re
import tempfile
import time
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


class NotReady(Exception):
    """Video can't be clipped yet (still live / VOD still processing). Retry next run."""


class Skip(Exception):
    """Video should never be clipped (e.g. too long). Mark as processed."""


_YT_CHANNEL = re.compile(r"^https?://(www\.|m\.)?youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+)/?$")
_TWITCH_CHANNEL = re.compile(r"^https?://(www\.)?twitch\.tv/([A-Za-z0-9_]+)/?$")


def expand_sources(sources: list[str]) -> list[str]:
    """A bare YouTube channel link covers both uploads and past live streams.
    A bare Twitch channel link means its past broadcasts."""
    out = []
    for s in sources:
        s = s.strip()
        if _YT_CHANNEL.match(s):
            out += [s.rstrip("/") + "/videos", s.rstrip("/") + "/streams"]
        elif (m := _TWITCH_CHANNEL.match(s)):
            out.append(f"https://www.twitch.tv/{m.group(2)}/videos?filter=archives&sort=time")
        else:
            out.append(s)
    return out


def list_new_videos(cfg: dict, state: dict) -> list[dict]:
    """Return [{id, url, title}] for unprocessed uploads across all sources."""
    found = []
    opts = {**_base_opts(), "extract_flat": "in_playlist",
            "playlistend": cfg["lookback_videos"]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for src in expand_sources(cfg["sources"]):
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
                if e.get("live_status") in ("is_live", "is_upcoming", "post_live"):
                    continue  # wait until the stream is over and the VOD is ready
                if any(f["id"] == vid for f in found):
                    continue
                url = e.get("url") or e.get("webpage_url") or vid
                if not str(url).startswith("http"):
                    url = f"https://www.youtube.com/watch?v={vid}"
                found.append({"id": vid, "url": url, "title": e.get("title") or vid,
                              "duration": dur or 0})
    return found


def probe_url(url: str) -> dict:
    with yt_dlp.YoutubeDL({**_base_opts(), "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)


def download(url: str, workdir: Path, cfg: dict) -> dict:
    """Download a video or stream VOD as mp4. Returns {id, title, path, duration, url}.
    Long streams are fetched at 720p to keep disk use and processing time down."""
    info = probe_url(url)
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise NotReady("stream is still live or the VOD is still processing")
    dur = info.get("duration") or 0
    ts = info.get("timestamp") or info.get("release_timestamp")
    # Twitch lists the VOD of a stream that's still going; its end is ~now.
    if ts and dur and time.time() - (ts + dur) < 20 * 60 and "twitch.tv" in url:
        raise NotReady("Twitch VOD looks like it is still recording")
    if dur > cfg["max_stream_hours"] * 3600:
        raise Skip(f"longer than max_stream_hours ({dur / 3600:.1f}h)")

    height = 720 if dur > cfg["long_video_minutes"] * 60 else 1080
    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_base_opts(),
        "format": (f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/bv*[height<={height}]+ba/"
                   f"b[height<={height}]/b"),
        "merge_output_format": "mp4",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,  # stream VODs come in many small pieces
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    return {"id": info["id"], "title": info.get("title") or info["id"],
            "path": path, "duration": info.get("duration") or dur,
            "url": info.get("webpage_url") or url}
