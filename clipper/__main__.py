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
from .chat import add_chat, chat_counts
from .gta_cues import classify_text
from .transcribe import add_energy, all_words, transcribe


def slugify(s: str, n: int = 50) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()[:n] or "video"


def post_text(clip: dict) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in clip["hashtags"])
    return f"{clip['caption']}\n\n{tags}".strip()


def apply_campaign(clip: dict, src: dict) -> dict:
    """Make every clip pass the campaign's caption rules (name + required hashtags)."""
    name, required = src.get("name"), src.get("hashtags") or []
    caption = clip["caption"].strip()
    if name and name.lower() not in caption.lower():
        caption = f"{name}: {caption}"
    tags = list(required)
    for t in clip["hashtags"]:
        t = "#" + t.lstrip("#").replace(" ", "")
        if t.lower() not in (x.lower() for x in tags):
            tags.append(t)
    return {**clip, "caption": caption, "hashtags": tags[:8]}


def process_video(video: dict, cfg: dict, keep_source: bool = False) -> Path | None:
    """video = {id, title, path, url?, source?}. Returns the output folder."""
    out_dir = ROOT / cfg["output_dir"] / f"{dt.date.today():%Y-%m-%d}_{slugify(video['title'])}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {video['title']} ===")
    src = video.get("source") or {}
    if src.get("name") or src.get("notes"):
        print(f"[campaign] {src.get('name') or src['url']}")
        cfg = {**cfg, "niche_notes": f"{cfg['niche_notes']}\n\nCampaign rules for this video "
               f"(streamer: {src.get('name') or 'see title'}): {src.get('notes')}".strip()}

    is_stream = (video.get("duration") or 0) > cfg["long_video_minutes"] * 60
    model = cfg["stream_whisper_model"] if is_stream else cfg["whisper_model"]
    t0 = time.time()
    segments = transcribe(video["path"], model, cfg["language"], out_dir / "transcript.json")
    print(f"[transcribe] took {(time.time() - t0) / 60:.0f} min with '{model}'")
    if not segments:
        print("[skip] no speech found")
        return None

    try:
        add_energy(video["path"], segments)
    except Exception as e:  # energy is a bonus signal; never fail a video over it
        print(f"[energy] skipped: {e}")
    for seg in segments:  # spoken GTA / gaming events (crash, chase, stunt, reaction...)
        cues = [c.category for c in classify_text(seg["text"])]
        if cues:
            seg["cues"] = cues
    spikes = []
    if video.get("twitch_vod"):
        off = video.get("offset") or 0
        counts = chat_counts(video["twitch_vod"], off, off + (video.get("duration") or segments[-1]["end"]))
        if counts:
            spikes = add_chat(segments, counts)
            print(f"[chat] {len(spikes)} spikes: " + ", ".join(f"{x['t'] // 60}m{x['t'] % 60:02d}s x{x['x']}" for x in spikes))
    if src.get("layout"):
        cfg = {**cfg, "layout": src["layout"]}
    picks = pick_clips(segments, video["title"], cfg, spikes)
    clips = snap_to_words(picks, all_words(segments), cfg)
    clips.sort(key=lambda c: -c["score"])
    weak = [c for c in clips if c.get("score", 10) < cfg["min_score"]]
    clips = [c for c in clips if c.get("score", 10) >= cfg["min_score"]]
    if weak:
        print(f"[select] dropped {len(weak)} weak moment(s) scoring under {cfg['min_score']}")
    clips = [apply_campaign(c, src) for c in clips[: cfg["max_clips_per_video"]]]
    print(f"[select] {len(picks)} suggested, {len(clips)} kept")

    manifest = []
    for i, clip in enumerate(clips, 1):
        name = f"clip_{i:02d}_{slugify(clip['title'], 40)}.mp4"
        layout = render_clip(video["path"], clip, out_dir / name, cfg, overlay=src.get("overlay"))
        text = post_text(clip)
        (out_dir / name).with_suffix(".txt").write_text(f"{clip['title']}\n\n{text}\n")
        print(f"[render] {name} ({clip['end'] - clip['start']:.0f}s, {layout}, score {clip['score']})")
        manifest.append({k: v for k, v in clip.items() if k != "words"} | {"file": name, "layout": layout})

    (out_dir / "manifest.json").write_text(json.dumps(
        {"source": video.get("url") or str(video["path"]), "title": video["title"],
         "clips": manifest}, indent=2))

    if deliver.telegram_enabled() and manifest:
        head = f"✂️ {len(manifest)} new clips from: {video['title']}"
        if src.get("reminder"):
            head += f"\n\n📌 {src['reminder']}"
        deliver.send_message(head)
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
    ap.add_argument("--campaign", help="apply this source's rules (its name in config.yaml)")
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
        state.setdefault("partial_urls", {})
        if args.cmd == "run":
            if not cfg["sources"] and not state["partial"]:
                print("No sources in config.yaml yet. Add a channel or playlist URL.")
                return
            todo = fetch.list_new_videos(cfg, state)[: cfg["max_videos_per_run"]]
            # also finish long videos that a previous run (e.g. one started by hand)
            # didn't get through
            for vid, vurl in state["partial_urls"].items():
                if vid in state["partial"] and not any(t["id"] == vid for t in todo):
                    todo.append({"id": vid, "url": vurl, "duration": 0})
            print(f"{len(todo)} new video(s) to clip")
        else:
            forced = None
            if args.campaign:
                forced = next((s for s in cfg["sources"]
                               if s["name"].lower() == args.campaign.lower()), None)
                print(f"[campaign] using {args.campaign} rules" if forced
                      else f"[campaign] no source named {args.campaign} in config.yaml")
            todo = [{"id": None, "url": u, "duration": 0, **({"source": forced} if forced else {})}
                    for u in args.urls]

        # GitHub stops a job after 6h. RUN_BUDGET_MINUTES (set by the workflow) makes
        # us leave a video for the next run instead of getting killed halfway through.
        budget = float(os.environ.get("RUN_BUDGET_MINUTES") or 0) * 60
        started = time.time()
        part_secs = cfg["stream_part_hours"] * 3600
        for item in todo:
            url = item["url"]
            key = item["id"] or url
            try:
                if not item["id"]:  # a URL run by hand: look up its id to resume parts
                    item["id"] = fetch.probe_url(url)["id"]
                # Long streams come in parts; keep going while there's time in this run.
                while True:
                    est = min(item["duration"] or part_secs, part_secs) * cfg["processing_ratio"] + 15 * 60
                    if budget and done and time.time() - started + est > budget:
                        print(f"[later] not enough time left for {url}, next run will take it")
                        break
                    part = state["partial"].get(item["id"], 0)
                    src = item.get("source") or fetch.find_source(cfg, url)
                    video = fetch.download(url, work, cfg, part, src)
                    if item.get("source", {}).get("name") or item.get("source", {}).get("notes"):
                        video["source"] = item["source"]
                    out = process_video(video, cfg)
                    shutil.rmtree(work, ignore_errors=True)
                    done.append(out)
                    state["failures"].pop(key, None)
                    if video["part"] + 1 < video["parts"]:
                        state["partial"][video["id"]] = video["part"] + 1
                        state["partial_urls"][video["id"]] = url
                        fetch.save_state(state)
                        continue  # next part (or NotReady if it's still being streamed)
                    state["partial"].pop(video["id"], None)
                    state["partial_urls"].pop(video["id"], None)
                    state["processed"][video["id"]] = {
                        "title": video["title"], "date": f"{dt.date.today()}",
                        "output": str(out.relative_to(ROOT)) if out else None}
                    break
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
