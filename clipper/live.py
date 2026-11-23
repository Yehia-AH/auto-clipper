"""Record a Twitch stream while it's live and clip every hour as soon as it's recorded.

  python -m clipper.live --check        # prints the first watched source that's live now
  python -m clipper live [--start-at T] # record it (called by .github/workflows/live.yml)

How it works:
- ffmpeg records the live broadcast, split into files at every full hour of the
  stream (hour 1 = first 60 min after the stream started, and so on).
- A finished hour is transcribed, clipped and sent to Telegram while the next hour
  is still recording, so nothing is missed.
- A GitHub job may run at most 6 h, so each run records about 3-4 h and, a few
  minutes before it stops, starts the next run, which picks up at the exact hour
  boundary.
- If ffmpeg drops (network blip, Twitch hiccup) it reconnects right away. The
  stream counts as over only after it's been offline for a few minutes in a row.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import fetch
from .config import ROOT, load_config

HOUR = int(os.environ.get("LIVE_HOUR_SECONDS") or 3600)   # tests use a few seconds
STALL_SECONDS = int(os.environ.get("LIVE_STALL_SECONDS") or 90)
RUN_RECORD_SECONDS = int(os.environ.get("LIVE_RUN_SECONDS") or 3 * 3600)
HANDOFF_EARLY = int(os.environ.get("LIVE_HANDOFF_EARLY") or 6 * 60)  # start next run this early
OFFLINE_CHECKS = 4          # offline this many checks in a row (1 min apart) = stream over
STAMP = "%Y%m%d%H%M%S"


def live_info(url: str) -> dict | None:
    """yt-dlp info for the channel's live broadcast, or None if it's offline."""
    try:
        info = fetch.probe_url(url)
    except Exception as e:
        if re.search(r"not (currently )?live|offline|does not exist", str(e), re.I):
            return None
        raise
    return info if info.get("is_live") else None


def watched_live_sources(cfg: dict) -> list[dict]:
    return [s for s in cfg["sources"] if s.get("live") and "twitch.tv" in s["url"]]


def find_live(cfg: dict) -> tuple[dict, dict] | None:
    for src in watched_live_sources(cfg):
        try:
            info = live_info(src["url"])
        except Exception as e:
            print(f"[live] could not check {src['url']}: {e}")
            continue
        if info:
            return src, info
        print(f"[live] {src.get('name') or src['url']} is offline")
    return None


def hour_of(t: float, stream_start: float) -> int:
    """1-based stream hour a moment belongs to (+5 s: splits land just after the boundary)."""
    return int((t - stream_start + 5) // HOUR) + 1


class Recorder(threading.Thread):
    """Records the stream into <dir>/rec_<UTC start time>.ts files, split at each
    full stream hour, until `stop_at` or until the stream ends."""

    def __init__(self, src: dict, info: dict, workdir: Path, height: int, stop_at: float,
                 stream_start: float, on_handoff=None):
        super().__init__(daemon=True)
        self.src, self.info, self.dir, self.height = src, info, workdir, height
        self.stop_at, self.stream_start, self.on_handoff = stop_at, stream_start, on_handoff
        self.done = threading.Event()
        self.ended = False      # True = the stream itself is over (not just this run)
        self.proc = None

    def _fresh_info(self) -> dict | None:
        misses = 0
        while time.time() < self.stop_at:
            try:
                info = live_info(self.src["url"])
            except Exception as e:
                print(f"[live] check failed: {e}")
                info = None
            if info:
                return info
            misses += 1
            if misses >= OFFLINE_CHECKS:
                return None
            time.sleep(60)
        return None

    def _handoff_watch(self):
        wait = self.stop_at - HANDOFF_EARLY - time.time()
        if wait > 0 and self.done.wait(wait):
            return  # stream ended before hand-off time
        if not self.done.is_set() and self.on_handoff:
            self.on_handoff(self.stop_at)

    def run(self):
        threading.Thread(target=self._handoff_watch, daemon=True).start()
        info, fails = self.info, 0
        try:
            while time.time() < self.stop_at - 5:
                if info is None:
                    info = self._fresh_info()
                    if info is None:
                        self.ended = time.time() < self.stop_at - 5
                        break
                url, headers, h = fetch.hls_format(info, self.height)
                cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin"]
                if headers:
                    cmd += ["-headers", headers]
                offset = int(self.stream_start) % HOUR
                cmd += ["-m3u8_hold_counters", "45", "-i", url, "-t", f"{self.stop_at - time.time():.0f}",
                        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                        "-f", "segment", "-segment_format", "mpegts",
                        "-segment_time", str(HOUR), "-segment_atclocktime", "1",
                        "-segment_clocktime_offset", str(offset),
                        "-reset_timestamps", "1", "-strftime", "1",
                        str(self.dir / f"rec_{STAMP}.ts")]
                print(f"[live] recording at {h}p until "
                      f"{dt.datetime.fromtimestamp(self.stop_at, dt.timezone.utc):%H:%M} UTC")
                t0 = time.time()
                self.proc = subprocess.Popen(cmd, env={**os.environ, "TZ": "UTC"})
                self._wait_or_stall(t0, STALL_SECONDS)
                if time.time() >= self.stop_at - 5:
                    break
                ran = time.time() - t0
                print(f"[live] recording stopped after {ran / 60:.0f} min (exit {self.proc.returncode}), "
                      "checking the stream...")
                fails = fails + 1 if ran < 60 else 0
                if fails >= 5:
                    time.sleep(30)  # don't hammer Twitch if something is really wrong
                info = None  # re-check: a blip reconnects, an ended stream stops
        finally:
            self.done.set()

    def _wait_or_stall(self, t0: float, stall: int = 90):
        """Wait for ffmpeg; kill it if the recording stops growing (a stream that ended
        or froze can leave ffmpeg waiting forever for new video)."""
        while self.proc.poll() is None:
            time.sleep(10)
            files = list(self.dir.glob("rec_*.ts"))
            newest = max((f.stat().st_mtime for f in files), default=t0)
            if time.time() - max(newest, t0) > stall:
                print(f"[live] no new video for {stall} s, reconnecting")
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.proc.kill()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def log_game(login: str, path: Path, stop: threading.Event, every: int = 300) -> None:
    from .chat import stream_game
    while not stop.is_set():
        game = stream_game(login)
        if game:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.time():.0f}\t{game}\n")
        stop.wait(every)


def game_share(path: Path, a: float, b: float, wanted: str | None) -> tuple[float, str]:
    """Share of category samples in [a, b) that match `wanted`, and the most seen
    category. ("", 1.0) when there's nothing to go on, so the hour is clipped."""
    from collections import Counter
    from .chat import matches_game
    if not wanted or not path.exists():
        return 1.0, ""
    games = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t, _, g = line.partition("\t")
        try:
            if a <= float(t) < b + 60:
                games.append(g)
        except ValueError:
            pass
    if len(games) < 3:
        return 1.0, ""
    share = sum(matches_game(g, wanted) for g in games) / len(games)
    return share, Counter(games).most_common(1)[0][0]


def recorded_files(workdir: Path) -> list[tuple[float, Path]]:
    out = []
    for p in workdir.glob("rec_*.ts"):
        try:
            t = dt.datetime.strptime(p.stem[4:], STAMP).replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
        out.append((t, p))
    return sorted(out)


def ready_hours(workdir: Path, stream_start: float, recording: bool) -> dict[int, list[Path]]:
    """Hours whose recording is finished: a later hour has started, or recording stopped."""
    by_hour: dict[int, list[Path]] = {}
    for t, p in recorded_files(workdir):
        by_hour.setdefault(hour_of(t, stream_start), []).append(p)
    if recording and by_hour:
        by_hour.pop(max(by_hour))  # still being written
    return by_hour


def join_hour(files: list[Path], out: Path) -> float:
    """Concatenate an hour's pieces into one mp4. Returns its length in seconds."""
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in files))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-nostdin", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", "-bsf:a", "aac_adtstoasc",
                    "-movflags", "+faststart", str(out)], check=True)
    lst.unlink(missing_ok=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def start_next_run(start_at: float) -> None:
    """Start the next recording run (GitHub stops jobs after 6 h)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print(f"[live] (local) would start the next run for {start_at:.0f}")
        return
    r = subprocess.run(["gh", "workflow", "run", "live.yml", "--ref", "main", "-R", repo,
                        "-f", f"start_at={int(start_at)}"], capture_output=True, text=True)
    print(f"[live] started the next recording run: {r.returncode == 0} {r.stderr.strip()[:200]}")
    if r.returncode == 0:
        (ROOT / ".handed_off").write_text(str(int(start_at)))  # the workflow then won't start a watcher


def publish_release(out_dir: Path, tag: str) -> None:
    """Put one hour's clips on GitHub right away (a backup, and lets Claude review
    each batch while the stream is still going)."""
    script = ROOT / "scripts" / "publish_releases.sh"
    if not (os.environ.get("GITHUB_ACTIONS") and script.exists()):
        return
    lst = ROOT / ".work" / f"release_{tag}.json"
    lst.write_text(json.dumps([str(out_dir)]))
    subprocess.run(["bash", str(script), str(lst), tag], cwd=ROOT)


def sync_state(state: dict) -> None:
    """Merge our progress with GitHub's copy and push it, then reload the merged
    copy (other runs number batches too, so stay in sync between hours)."""
    fetch.save_state(state)
    script = ROOT / "scripts" / "push_state.sh"
    if os.environ.get("GITHUB_ACTIONS") and script.exists():
        subprocess.run(["bash", str(script)], cwd=ROOT)
        state.clear()
        state.update(fetch.load_state())


def record_and_clip(cfg: dict, start_at: float | None, process_video, next_batch, record,
                    state: dict) -> list[Path]:
    from . import deliver
    if start_at and start_at - time.time() > 0:
        wait = start_at - time.time()
        print(f"[live] continuing a recording: waiting {wait / 60:.1f} min for the hour boundary")
        time.sleep(wait)
    if cfg.get("paused"):
        print("[live] paused in config.yaml, not recording")
        return []
    found = find_live(cfg)
    if not found:
        print("[live] nobody is live, nothing to record")
        return []
    src, info = found
    sid = str(info.get("id"))
    stream_start = float(info.get("timestamp") or time.time())
    sessions = state.setdefault("live_sessions", {})
    new_session = sid not in sessions
    sessions[sid] = {**sessions.get(sid, {}), "start": int(stream_start), "source": src["url"],
                     "title": info.get("title") or "", "seen": int(time.time())}
    sync_state(state)
    name = src.get("name") or src["url"]
    if new_session and deliver.telegram_enabled():
        deliver.send_message(f"🔴 {name} is live: recording it and sending clips about every hour.\n"
                             f"{info.get('title') or ''}")

    now = time.time()
    # stop on a stream-hour boundary roughly RUN_RECORD_SECONDS from now
    k = int((now + RUN_RECORD_SECONDS - stream_start) // HOUR) + 1
    stop_at = stream_start + k * HOUR
    print(f"[live] {name}: stream started "
          f"{dt.datetime.fromtimestamp(stream_start, dt.timezone.utc):%Y-%m-%d %H:%M} UTC, "
          f"now in hour {hour_of(now, stream_start)}; this run records until hour {k} ends")

    workdir = ROOT / ".work" / f"live_{sid}"
    workdir.mkdir(parents=True, exist_ok=True)
    rec = Recorder(src, info, workdir, cfg.get("max_height", 1080), stop_at, stream_start,
                   on_handoff=start_next_run)
    rec.start()
    from .chat import LiveChat
    chat_log = workdir / "chat.tsv"
    slug = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", src["url"])
    chat = LiveChat(slug.group(1), chat_log).start() if slug else None
    # note the stream's Twitch category every 5 min: hours spent on another game
    # (e.g. Fortnite before GTA) are skipped before any Claude call
    game_log = workdir / "game.tsv"
    if slug and src.get("require_game"):
        threading.Thread(target=log_game, args=(slug.group(1), game_log, rec.done),
                         daemon=True).start()

    done, handled = [], set()
    min_len = cfg["min_source_minutes"] * 60
    while True:
        recording = not rec.done.is_set()
        hours = ready_hours(workdir, stream_start, recording)
        todo = [h for h in sorted(hours) if h not in handled]
        if not todo and not recording:
            break
        if not todo:
            time.sleep(20)
            continue
        h = todo[0]
        handled.add(h)
        starts = {hh: min(t for t, p in recorded_files(workdir)
                          if hour_of(t, stream_start) == hh) for hh in hours}
        mp4 = workdir / f"hour_{h}.mp4"
        try:
            length = join_hour(hours[h], mp4)
            for p in hours[h]:
                p.unlink(missing_ok=True)
            if length < min_len:
                print(f"[live] hour {h}: only {length / 60:.0f} min recorded here, skipping")
                continue
            share, seen = game_share(game_log, starts[h], starts[h] + length, src.get("require_game"))
            if seen and share < 0.2:
                print(f"[live] hour {h}: not {src['require_game']} (category: {seen}), skipped "
                      "without calling Claude")
                if deliver.telegram_enabled():
                    deliver.send_message(f"🎮 {name} hour {h}: playing {seen}, not "
                                         f"{src['require_game']}. Skipped (no API cost).")
                continue
            print(f"[live] hour {h}: {length / 60:.0f} min recorded, clipping it")
            video = {"id": f"live{sid}", "title": f"{info.get('title') or name} (part {h} live)",
                     "path": mp4, "duration": length, "url": src["url"], "part": h - 1,
                     "parts": h + 1, "offset": 0, "twitch_vod": None, "source": src,
                     "chat_log": chat_log, "start_epoch": starts[h]}
            out = process_video(video, cfg, next_batch=next_batch, record=record)
            done.append(out)
            if out:
                publish_release(out, f"h{h}")
            elif video.get("away") and deliver.telegram_enabled():
                deliver.send_message(f"💤 {name} was on a break in hour {h} (hardly talking), "
                                     "skipped it. Still recording.")
            sessions = state.setdefault("live_sessions", {})
            sessions.setdefault(sid, {})["hours_clipped"] = sorted(
                set(sessions[sid].get("hours_clipped", [])) | {h})
        except Exception as e:
            print(f"[live] hour {h} failed: {e}")
            if deliver.telegram_enabled():
                deliver.send_message(f"⚠️ {name} live hour {h} couldn't be clipped: {str(e)[:300]}")
        finally:
            mp4.unlink(missing_ok=True)
            sync_state(state)

    if chat:
        chat.stop()
    if rec.ended:
        print(f"[live] {name}: stream is over")
        if deliver.telegram_enabled():
            deliver.send_message(f"⏹ {name}'s stream ended. All recorded hours are clipped.")
    return [d for d in done if d]


if __name__ == "__main__" and "--check" in sys.argv:
    _cfg = load_config()
    if _cfg.get("paused"):
        print("PAUSED (paused: true in config.yaml)")
        print("LIVE=")
        sys.exit(0)
    hit = find_live(_cfg)
    print(f"LIVE={hit[0]['url'] if hit else ''}")
