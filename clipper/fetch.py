"""Find new uploads on the watched sources and download them with yt-dlp."""
import json
import math
import os
import contextlib
import re
import signal
import subprocess
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


def expand_sources(sources: list) -> list[tuple[str, dict]]:
    """A bare YouTube channel link covers both uploads and past live streams.
    A bare Twitch channel link means its past broadcasts.
    Returns [(url_to_scan, source_settings)]."""
    out = []
    for src in sources:
        if isinstance(src, str):
            src = {"url": src}
        s = src["url"].strip()
        if _YT_CHANNEL.match(s):
            out += [(s.rstrip("/") + "/videos", src), (s.rstrip("/") + "/streams", src)]
        elif (m := _TWITCH_CHANNEL.match(s)):
            out.append((f"https://www.twitch.tv/{m.group(2)}/videos?filter=archives&sort=time", src))
        else:
            out.append((s, src))
    return out


def _channel_slug(url: str) -> str | None:
    m = re.search(r"(?:youtube\.com/@|twitch\.tv/|kick\.com/)([A-Za-z0-9_.\-]+)", url or "")
    return m.group(1).lower() if m and m.group(1).lower() not in ("videos", "watch") else None


def find_source(cfg: dict, url: str, info: dict | None = None) -> dict:
    """Match a video to its source's campaign settings (by channel name)."""
    names = {n.lower() for n in [
        _channel_slug(url) or "",
        *((info or {}).get(k) or "" for k in ("uploader_id", "channel", "uploader", "channel_id")),
    ] if n}
    names |= {n.lstrip("@") for n in names}
    for src in cfg["sources"]:
        slug = _channel_slug(src["url"])
        if slug and slug in names:
            return src
    return {"url": url, "name": "", "hashtags": [], "notes": "", "overlay": "", "reminder": ""}


def list_new_videos(cfg: dict, state: dict) -> list[dict]:
    """Return [{id, url, title, duration, source}] for unclipped videos across all sources."""
    found = []
    opts = {**_base_opts(), "extract_flat": "in_playlist",
            "playlistend": cfg["lookback_videos"]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        finished = state.get("finished_sources", {})
        watched = [s for s in cfg["sources"] if s.get("auto", True) and s["url"] not in finished]
        for src, settings in expand_sources(watched):
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
                if e.get("live_status") in ("is_upcoming", "post_live") or (
                        e.get("live_status") == "is_live" and "twitch.tv" not in src):
                    continue  # wait until the stream is over and the VOD is ready
                if "twitch.tv" in src and not re.fullmatch(r"v?\d+", str(vid)):
                    continue  # the channel's live broadcast itself, not a saved VOD
                if "twitch.tv" in src and settings.get("live") and e.get("live_status") == "is_live":
                    continue  # the live recorder (live.yml) records this one
                if before_start(e, settings):
                    continue  # older than the campaign's start date
                if any(f["id"] == vid for f in found):
                    continue
                url = e.get("url") or e.get("webpage_url") or vid
                if not str(url).startswith("http"):
                    url = f"https://www.youtube.com/watch?v={vid}"
                found.append({"id": vid, "url": url, "title": e.get("title") or vid,
                              "duration": dur or 0, "source": settings})
    for f_ in found:
        print(f"[fetch] to clip: {f_['url']} ({f_['title'][:60]})")
    return found


DOWNLOAD_LIMIT = 45 * 60  # seconds; a stuck download is dropped and retried next run


@contextlib.contextmanager
def time_limit(seconds: int, what: str):
    """Abort the block if it takes longer than `seconds` (a hung download once ate a
    whole 6-hour run). Raises TimeoutError, which the caller counts as a failure."""
    def _alarm(signum, frame):
        raise TimeoutError(f"{what} took longer than {seconds // 60} min, gave up")
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def probe_url(url: str) -> dict:
    with yt_dlp.YoutubeDL({**_base_opts(), "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)


def download(url: str, workdir: Path, cfg: dict, part: int = 0,
             src_settings: dict | None = None) -> dict:
    """Download a video or stream VOD as mp4.
    Returns {id, title, path, duration, url, part, parts}.
    Long streams are fetched at 720p. Marathon streams longer than max_stream_hours are
    split into parts of that length; `part` picks which one (one part per run)."""
    print(f"[fetch] checking {url}" + (f" (hour {part + 1})" if part else ""))
    with time_limit(5 * 60, "reading the video info"):
        info = probe_url(url)
    is_twitch = "twitch.tv" in url
    live = info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live")
    if live and not is_twitch:
        raise NotReady("stream is still live or the VOD is still processing")
    if recorded_live(info, url):
        raise Skip("already recorded and clipped while it was live")
    if src_settings and before_start(info, src_settings):
        raise Skip(f"recorded before the campaign start ({src_settings.get('since')})")
    dur = info.get("duration") or 0
    ts = info.get("timestamp") or info.get("release_timestamp")
    # A Twitch VOD of a stream that's still going is marked live (and its end is ~now).
    # For marathons we clip the hours that are already recorded instead of waiting days.
    recording = is_twitch and bool(live or (ts and dur and time.time() - (ts + dur) < 20 * 60))
    if recording and not dur:
        raise NotReady("stream is live but its length isn't known yet")
    part_len = cfg["stream_part_hours"] * 3600
    split = recording or part > 0 or dur > cfg["max_stream_hours"] * 3600
    if recording:
        ready = int(dur // part_len)  # fully recorded parts so far
        if part >= ready:
            raise NotReady(f"stream is live; the next {cfg['stream_part_hours']}h part isn't "
                           f"finished yet ({dur / 3600:.1f}h recorded)")
        parts = ready + 1  # total unknown while live, so never 'done' yet
    elif split:
        parts = max(1, math.ceil((dur - 60) / part_len))
    else:
        parts = 1
    if part >= parts:
        raise Skip("all parts already clipped")
    start, end = (part * part_len, min(dur, (part + 1) * part_len)) if split else (0, dur)

    height = cfg.get("max_height", 1080)  # 1080p: the webcam and game get blown up to fill a phone screen
    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_base_opts(),
        "format": (f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/bv*[height<={height}]+ba/"
                   f"b[height<={height}]/b"),
        "merge_output_format": "mp4",
        "outtmpl": str(workdir / f"%(id)s_p{part}.%(ext)s"),
        "noplaylist": True,
        "concurrent_fragment_downloads": 8,  # stream VODs come in many small pieces
    }
    print(f"[fetch] downloading {info.get('id')} {start / 3600:.1f}h-{(end or dur) / 3600:.1f}h "
          f"at {height}p (limit {DOWNLOAD_LIMIT // 60} min)")
    if recording:
        # yt-dlp can't cut a range out of a live recording, so cut it from the HLS
        # playlist ourselves (it already holds every segment recorded so far)
        path = workdir / f"{info['id']}_p{part}.mp4"
        cut_hls(info, height, start, end - start, path)
    else:
        if split:
            opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(start, end)])
        opts["socket_timeout"] = 60
        with time_limit(DOWNLOAD_LIMIT, "downloading the video"), yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    title = info.get("title") or info["id"]
    if split:
        total = "live" if recording else f"of {parts}"
        title = f"{title} (part {part + 1} {total})"
        print(f"[fetch] long stream ({dur / 3600:.1f}h{', still live' if recording else ''}): "
              f"clipping {start / 3600:.1f}h-{end / 3600:.1f}h")
    return {"id": info["id"], "title": title, "path": path,
            "duration": (end - start) if split else (info.get("duration") or dur),
            "url": info.get("webpage_url") or url, "part": part, "parts": parts,
            "offset": start, "twitch_vod": info["id"] if is_twitch else None,
            "source": find_source(cfg, url, info)}


def before_start(info: dict, settings: dict) -> bool:
    """True if a video was recorded before the source's `since` date (YYYY-MM-DD)."""
    since = str(settings.get("since") or "").strip()
    if not since:
        return False
    ts = info.get("timestamp") or info.get("release_timestamp")
    if ts:
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
    elif info.get("upload_date"):
        d = str(info["upload_date"])
        day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    else:
        return False  # unknown date: let it through
    return day < since


def hls_format(info: dict, height: int) -> tuple[str, str, int]:
    """Best HLS (m3u8) video format up to `height`: (url, ffmpeg headers, height)."""
    fmts = [f for f in info.get("formats") or []
            if "m3u8" in (f.get("protocol") or "") and f.get("vcodec") != "none"]
    if not fmts:
        raise RuntimeError("no HLS format found for the stream")
    ok = [f for f in fmts if (f.get("height") or 0) <= height] or fmts
    fmt = max(ok, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    headers = "".join(f"{k}: {v}\r\n" for k, v in (fmt.get("http_headers") or {}).items())
    return fmt["url"], headers, fmt.get("height") or 0


def recorded_live(info: dict, url: str) -> bool:
    """True if this Twitch VOD is a stream the live recorder already recorded
    (same channel, started within 30 min of a recorded session)."""
    ts = info.get("timestamp") or info.get("release_timestamp")
    if not ts or "twitch.tv" not in url:
        return False
    names = {str(info.get(k) or "").lower() for k in ("uploader_id", "channel", "uploader")} - {""}
    for sess in load_state().get("live_sessions", {}).values():
        if _channel_slug(sess.get("source", "")) in names and abs(sess.get("start", 0) - ts) < 30 * 60:
            return True
    return False


def cut_hls(info: dict, height: int, start: float, length: float, out: Path) -> None:
    """Copy [start, start+length) out of an HLS (m3u8) format with ffmpeg."""
    url, headers, h = hls_format(info, height)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin"]
    if headers:
        cmd += ["-headers", headers]
    cmd += ["-ss", f"{start:.0f}", "-i", url, "-t", f"{length:.0f}",
            "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart", str(out)]
    print(f"[fetch] cutting {start / 3600:.1f}h-{(start + length) / 3600:.1f}h "
          f"from the live recording ({h}p)")
    try:
        subprocess.run(cmd, check=True, timeout=DOWNLOAD_LIMIT)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"cutting from the live recording took longer than "
                           f"{DOWNLOAD_LIMIT // 60} min, gave up") from None
