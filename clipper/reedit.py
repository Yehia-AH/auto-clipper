"""Re-edit clips that were already made: find each clip's exact spot in the Twitch
VOD by matching its audio, cut that same moment again and render it with the
current edits (unique zoom/colour, progress bar, captions...).

  python -m clipper.reedit requests/reedit.json

reedit.json: {"vod": "<twitch vod url>", "label": "re-edits",
              "clips": [{"tag": release tag, "mp4": asset name, "hour": stream hour,
                         "title", "caption", "x_caption", "hashtags": [...]}]}
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import deliver, fetch
from .config import ROOT, load_config

RATE = 4000  # Hz, plenty for lining audio up
MARGIN = 10 * 60  # search this far around the clip's stream hour


def _decode(cmd: list[str]) -> np.ndarray:
    raw = subprocess.run(cmd, check=True, capture_output=True, timeout=1800).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def file_audio(path: Path) -> np.ndarray:
    return _decode(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn",
                    "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"])


def vod_audio(info: dict, start: float, length: float, work: Path) -> np.ndarray:
    """Audio of [start, start+length) of the VOD, fetched segment by segment."""
    import requests
    fmts = [f for f in info.get("formats") or [] if "m3u8" in (f.get("protocol") or "")]
    audio_only = [f for f in fmts if f.get("vcodec") == "none"]
    fmt = (audio_only or sorted(fmts, key=lambda f: f.get("height") or 0))[0]
    text = requests.get(fmt["url"], timeout=60).text
    playlist, trim = fetch.sub_playlist(text, fmt["url"], start, length)
    local = work / "search.m3u8"
    local.write_text(playlist)
    return _decode(["ffmpeg", "-nostdin", "-loglevel", "error",
                    "-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-i", str(local),
                    "-ss", f"{trim:.2f}", "-t", f"{length:.0f}", "-vn", "-ac", "1",
                    "-ar", str(RATE), "-f", "s16le", "-"])


def locate(clip: np.ndarray, hay: np.ndarray) -> tuple[float, float]:
    """Offset (s) of `clip` inside `hay` by FFT cross-correlation, plus a confidence
    score (peak height vs the typical correlation; > ~6 is a sure match)."""
    c = clip - clip.mean()
    h = hay - hay.mean()
    n = 1 << int(np.ceil(np.log2(len(h) + len(c))))
    corr = np.fft.irfft(np.fft.rfft(h, n) * np.conj(np.fft.rfft(c, n)), n)[: len(h) - len(c) + 1]
    # normalise by the energy of each window so loud stretches don't win by volume
    cs = np.concatenate([[0.0], np.cumsum(h.astype(np.float64) ** 2)])
    e = np.sqrt(cs[len(c):] - cs[:-len(c)] + 1e-9)
    score = corr / (e * (np.linalg.norm(c) + 1e-9))
    i = int(np.argmax(score))
    conf = float(score[i] / (np.median(np.abs(score)) + 1e-9))
    return i / RATE, conf


def main() -> None:
    req = json.loads(Path(sys.argv[1]).read_text())
    cfg = load_config()
    src = next((s for s in cfg["sources"] if s["name"].lower() == req.get("source", "clix")), {})
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    work = ROOT / ".work" / "reedit"
    work.mkdir(parents=True, exist_ok=True)
    info = fetch.probe_url(req["vod"])
    print(f"[reedit] {info.get('title')} ({(info.get('duration') or 0) / 3600:.1f}h), "
          f"{len(req['clips'])} clips")

    from .__main__ import render_clip, slugify
    from .transcribe import all_words, transcribe

    state = fetch.load_state()
    state["batch_counter"] = max(state.get("batch_counter", 0), fetch.remote_batch_counter()) + 1
    batch = state["batch_counter"]
    fetch.save_state(state)
    fetch.claim_state()
    out_dir = ROOT / cfg["output_dir"] / f"reedit_batch{batch}"
    out_dir.mkdir(parents=True, exist_ok=True)

    done, failed = [], []
    for i, c in enumerate(req["clips"], 1):
        cid = f"{batch}.{i}"
        try:
            old = work / f"old_{i}.mp4"
            subprocess.run(["gh", "release", "download", c["tag"], "-R", repo, "-p", c["mp4"],
                            "-O", str(old), "--clobber"], check=True)
            clip_audio = file_audio(old)
            dur = len(clip_audio) / RATE
            lo = max(0.0, (c["hour"] - 1) * 3600 - MARGIN)
            hay = vod_audio(info, lo, 3600 + 2 * MARGIN, work)
            off, conf = locate(clip_audio, hay)
            start = lo + off
            print(f"[reedit] {c['title']}: found at {start / 3600:.3f}h (match {conf:.1f})")
            if conf < 5:
                raise RuntimeError(f"couldn't find it in the VOD reliably (match {conf:.1f})")

            # cut the moment (+2 s each side) and caption it again
            seg = work / f"seg_{i}.mp4"
            fetch.cut_hls(info, cfg.get("max_height", 1080), max(0, start - 2), dur + 4, seg)
            segs = transcribe(seg, cfg["whisper_model"], cfg["language"], work / f"t_{i}.json")
            lead = min(2.0, start)
            words = [w for w in all_words(segs) if lead - 0.3 <= w["start"] and w["end"] <= lead + dur + 0.3]
            clip = {"start": lead, "end": lead + dur, "title": c["title"], "words": words,
                    "caption": c["caption"], "x_caption": c.get("x_caption", ""),
                    "hashtags": c["hashtags"], "score": c.get("score", 0)}
            name = f"clip_{i:02d}_{slugify(c['title'], 40)}.mp4"
            render_clip(seg, clip, out_dir / name, cfg, webcam=src.get("webcam"),
                        gameplay_only=bool(src.get("require_game")))
            from .__main__ import post_text
            text = post_text(clip)
            (out_dir / name).with_suffix(".txt").write_text(f"Clip {cid} (re-edit of {c['id']})\n"
                                                            f"{c['title']}\n\n{text}\n")
            done.append((cid, c, out_dir / name, text))
        except Exception as e:
            print(f"[reedit] {c['title']} failed: {e}")
            failed.append(c["title"])
        finally:
            for p in work.glob(f"*_{i}.*"):
                p.unlink(missing_ok=True)

    (out_dir / "manifest.json").write_text(json.dumps(
        {"title": f"Batch {batch} · {src.get('name', '')} · {req.get('label', 're-edits')}",
         "clips": [{"id": cid, "title": c["title"], "file": p.name} for cid, c, p, _ in done]}, indent=2))
    state = fetch.load_state()
    state.setdefault("clips", []).extend(
        {"id": cid, "title": c["title"], "score": c.get("score", 0), "streamer": src.get("name", ""),
         "at": int(time.time())} for cid, c, _, _ in done)
    fetch.save_state(state)
    (ROOT / ".last_run.json").write_text(json.dumps([str(out_dir)] if done else []))

    if deliver.telegram_enabled():
        head = (f"✨ Batch {batch} · {src.get('name', '')} · {req.get('label', 're-edits')} · "
                f"{len(done)} clips, re-edited with the new look (zoom punch-ins, own colour, "
                "progress bar). Use these for Instagram.")
        if failed:
            head += "\n\nCouldn't re-edit: " + ", ".join(failed)
        deliver.send_message(head)
        for cid, c, path, text in done:
            deliver.send_clip(path, f"✨ {cid} (re-edit of {c['id']})\n{c['title']}\n\n{text}")
    print(f"[reedit] done: {len(done)} ok, {len(failed)} failed")


if __name__ == "__main__":
    main()
