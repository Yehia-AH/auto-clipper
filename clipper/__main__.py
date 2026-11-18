"""Auto Clipper.

  python -m clipper run              # clip new uploads from the sources in config.yaml
  python -m clipper url <URL> [...]  # clip specific videos
  python -m clipper file <path>      # clip a local video file
"""
import argparse
import datetime as dt
import json
import re
import shutil
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

    segments = transcribe(video["path"], cfg["whisper_model"], cfg["language"],
                          out_dir / "transcript.json")
    if not segments:
        print("[skip] no speech found")
        return None

    picks = pick_clips(segments, video["title"], cfg)
    clips = snap_to_words(picks, all_words(segments), cfg)
    clips.sort(key=lambda c: -c["score"])
    print(f"[select] {len(picks)} suggested, {len(clips)} usable")

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
        if args.cmd == "run":
            if not cfg["sources"]:
                print("No sources in config.yaml yet. Add a channel or playlist URL.")
                return
            todo = fetch.list_new_videos(cfg, state)[: cfg["max_videos_per_run"]]
            print(f"{len(todo)} new video(s) to clip")
            urls = [v["url"] for v in todo]
        else:
            urls = args.urls
        for url in urls:
            try:
                video = fetch.download(url, work)
                out = process_video(video, cfg)
                state["processed"][video["id"]] = {
                    "title": video["title"], "date": f"{dt.date.today()}",
                    "output": str(out.relative_to(ROOT)) if out else None}
                fetch.save_state(state)  # save after each video so progress isn't lost
                done.append(out)
            except Exception as e:
                print(f"[error] {url}: {e}")
                if deliver.telegram_enabled():
                    deliver.send_message(f"⚠️ Clipper failed on {url}: {str(e)[:300]}")
            finally:
                shutil.rmtree(work, ignore_errors=True)

    done = [d for d in done if d]
    # GitHub Actions reads this to publish releases
    (ROOT / ".last_run.json").write_text(json.dumps([str(d) for d in done]))
    print(f"\nDone. {len(done)} video(s) clipped.")


if __name__ == "__main__":
    main()
