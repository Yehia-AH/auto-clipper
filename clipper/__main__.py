"""Auto Clipper.

  python -m clipper run              # clip new uploads from the sources in config.yaml
  python -m clipper url <URL> [...]  # clip specific videos
  python -m clipper file <path>      # clip a local video file
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import deliver, fetch
from .config import ROOT, load_config
from .render import render_clip
from .highlights import pick_clips, snap_to_words
from .transcribe import all_words, transcribe


def slugify(s: str, n: int = 50) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:n] or "video"


def post_text(clip: dict) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in clip["hashtags"])
    return f"{clip['caption']}\n\n{tags}".strip()


def process_video(video: dict, cfg: dict, keep_source: bool = False) -> Path | None:
    """video = {id, title, path, url?}. Returns the output folder."""
    out_dir = ROOT / cfg["output_dir"] / f"{dt.date.today():%Y-%m-%d}_{slugify(video['title'])}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {video['title']} ===")

    is_stream = (video.get("duration") or 0) > cfg["long_video_minutes"] * 60
    model = cfg["stream_whisper_model"] if is_stream else cfg["whisper_model"]
    t0 = time.time()
    segments = transcribe(video["path"], model, cfg["language"], out_dir / "transcript.json")
    print(f"[transcribe] took {(time.time() - t0) / 60:.0f} min with '{model}'")
    if not segments:
        print("[skip] no speech found")
        return None

    picks = pick_clips(segments, video["title"], cfg)
    clips = snap_to_words(picks, all_words(segments), cfg)
    clips.sort(key=lambda c: -c["score"])
    clips = clips[: cfg["max_clips_per_video"]]
    print(f"[select] {len(picks)} suggested, {len(clips)} kept")

    manifest = []
    for i, clip in enumerate(clips, 1):
        name = f"clip_{i:02d}_{slugify(clip['title'], 40)}.mp4"
        layout = render_clip(video["path"], clip, out_dir / name, cfg)
        text = post_text(clip)
        (out_dir / name).with_suffix(".txt").write_text(f"{clip['title']}\n\n{text}\n")
        print(f"[render] {name} ({clip['end'] - clip['start']:.0f}s, {layout}, score {clip['score']})")
        manifest.append({k: v for k, v in clip.items() if k != "words"} | {"file": name, "layout": layout})

    (out_dir / "manifest.json").write_text(json.dumps(
        {"source": video.get("url") or str(video["path"]), "title": video["title"],
         "clips": manifest}, indent=2))

    if deliver.telegram_enabled() and manifest:
        deliver.send_message(f"✂️ {len(manifest)} new clips from: {video['title']}")
        for m in manifest:
            deliver.send_clip(out_dir / m["file"], f"{m['title']}\n\n{post_text(m)}")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    u = sub.add_parser("url")
    u.add_argument("urls", nargs="+")
    f = sub.add_parser("file")
    f.add_argument("path")
    f.add_argument("--title")
    ap.add_argument("--clips", type=int, help="override clips_per_video")
    args = ap.parse_args()

    cfg = load_config()
    if args.clips:
        cfg["clips_per_video"] = args.clips
    work = ROOT / ".work"
    done = []

    if args.cmd == "file":
        p = Path(args.path)
        out = process_video({"id": p.stem, "title": args.title or p.stem, "path": p}, cfg)
        done.append(out)
    else:
        state = fetch.load_state()
        state.setdefault("failures", {})
        state.setdefault("partial", {})
        if args.cmd == "run":
            if not cfg["sources"]:
                print("No sources in config.yaml yet. Add a channel or playlist URL.")
                return
            todo = fetch.list_new_videos(cfg, state)[: cfg["max_videos_per_run"]]
            print(f"{len(todo)} new video(s) to clip")
        else:
            todo = [{"id": None, "url": u, "duration": 0} for u in args.urls]

        # GitHub stops a job after 6h. RUN_BUDGET_MINUTES (set by the workflow) makes
        # us leave a video for the next run instead of getting killed halfway through.
        budget = float(os.environ.get("RUN_BUDGET_MINUTES") or 0) * 60
        started = time.time()
        for item in todo:
            url = item["url"]
            est = min(item["duration"], cfg["max_stream_hours"] * 3600) * cfg["processing_ratio"] + 15 * 60
            if budget and done and time.time() - started + est > budget:
                print(f"[later] not enough time left for {url}, next run will take it")
                continue
            key = item["id"] or url
            part = state["partial"].get(item["id"], 0) if item["id"] else 0
            try:
                video = fetch.download(url, work, cfg, part)
                out = process_video(video, cfg)
                if video["part"] + 1 < video["parts"]:
                    # marathon stream: next run picks up the next part
                    state["partial"][video["id"]] = video["part"] + 1
                else:
                    state["partial"].pop(video["id"], None)
                    state["processed"][video["id"]] = {
                        "title": video["title"], "date": f"{dt.date.today()}",
                        "output": str(out.relative_to(ROOT)) if out else None}
                state["failures"].pop(key, None)
                done.append(out)
            except fetch.NotReady as e:
                print(f"[later] {url}: {e}")
            except fetch.Skip as e:
                print(f"[skip] {url}: {e}")
                if item["id"]:
                    state["processed"][item["id"]] = {"date": f"{dt.date.today()}", "skipped": str(e)}
            except Exception as e:
                print(f"[error] {url}: {e}")
                n = state["failures"][key] = state["failures"].get(key, 0) + 1
                if n >= 3 and item["id"]:  # stop retrying a video that keeps failing
                    state["processed"][item["id"]] = {"date": f"{dt.date.today()}", "error": str(e)[:300]}
                if deliver.telegram_enabled():
                    deliver.send_message(f"⚠️ Clipper failed on {url} (try {n}/3): {str(e)[:300]}")
            finally:
                fetch.save_state(state)  # save after each video so progress isn't lost
                shutil.rmtree(work, ignore_errors=True)

    done = [d for d in done if d]
    # GitHub Actions reads this to publish releases
    (ROOT / ".last_run.json").write_text(json.dumps([str(d) for d in done]))
    print(f"\nDone. {len(done)} video(s) clipped.")


if __name__ == "__main__":
    main()
