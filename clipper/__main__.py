"""Auto Clipper.

  python -m clipper run              # clip new uploads from the sources in config.yaml
  python -m clipper url <URL> [...]  # clip specific videos
  python -m clipper file <path>      # clip a local video file
  python -m clipper live             # record a watched streamer while live, clip every hour
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


def batch_label(video: dict, src: dict) -> str:
    """Short human name for a batch, e.g. "Clix · hour 3" or "SypherPK · FINDING THE…"."""
    who = src.get("name") or video.get("uploader") or ""
    base = re.sub(r"\s*\(part \d+ (?:live|of \d+)\)$", "", video["title"])
    if video.get("parts", 1) > 1 or video.get("part"):
        what = f"hour {video['part'] + 1}"
    else:
        what = base[:45] + ("…" if len(base) > 45 else "")
    return " · ".join(x for x in (who, what) if x)


def process_video(video: dict, cfg: dict, keep_source: bool = False, next_batch=None,
                  record=None) -> Path | None:
    """video = {id, title, path, url?, source?}. Returns the output folder."""
    # Unique per video AND per part: long titles get cut short by slugify, and
    # parts of one stream must never share a folder (or a cached transcript).
    part = f"_p{video['part'] + 1}" if video.get("parts", 1) > 1 or video.get("part") else ""
    out_dir = (ROOT / cfg["output_dir"] /
               f"{dt.date.today():%Y-%m-%d}_{slugify(video['title'], 40)}_{slugify(str(video['id']), 20)}{part}")
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
    # On a break (asleep on stream, BRB screen, AFK): hardly any talking. Skip it
    # instead of asking Claude to find clips in silence.
    words = sum(len(s["text"].split()) for s in segments)
    minutes = max((video.get("duration") or segments[-1]["end"]) / 60, 1)
    if words / minutes < cfg.get("min_words_per_minute", 20):
        print(f"[skip] streamer seems to be away ({words} words in {minutes:.0f} min)")
        video["away"] = True
        return None

    try:
        markers = add_energy(video["path"], segments)
        if markers:  # loud gameplay with no talking: show Claude where it happens
            segments = sorted(segments + markers, key=lambda s: s["start"])
            print(f"[energy] {len(markers)} loud no-talking game moments")
    except Exception as e:  # energy is a bonus signal; never fail a video over it
        print(f"[energy] skipped: {e}")
    for seg in segments:  # spoken GTA / gaming events (crash, chase, stunt, reaction...)
        cues = [c.category for c in classify_text(seg["text"])]
        if cues:
            seg["cues"] = cues
    spikes = []
    if video.get("chat_log"):  # recorded live: we logged chat ourselves
        from .chat import live_counts
        counts = live_counts(video["chat_log"], video["start_epoch"],
                             video["start_epoch"] + (video.get("duration") or segments[-1]["end"]))
        if counts:
            spikes = add_chat(segments, counts)
            print(f"[chat] {len(spikes)} spikes: " + ", ".join(f"{x['t'] // 60}m{x['t'] % 60:02d}s x{x['x']}" for x in spikes))
    elif video.get("twitch_vod"):
        off = video.get("offset") or 0
        counts = chat_counts(video["twitch_vod"], off, off + (video.get("duration") or segments[-1]["end"]))
        if counts:
            spikes = add_chat(segments, counts)
            print(f"[chat] {len(spikes)} spikes: " + ", ".join(f"{x['t'] // 60}m{x['t'] % 60:02d}s x{x['x']}" for x in spikes))
    if src.get("layout"):
        cfg = {**cfg, "layout": src["layout"]}
    if video.get("parts", 1) > 1 or video.get("part"):
        # one hour of a long stream: ask for a few, keep only the best
        cfg = {**cfg, "clips_per_video": cfg["stream_clips_per_hour"] + 2}
    if cfg.get("find"):
        # looking for one specific moment the user described: no quality filters
        from .highlights import find_moment
        picks = find_moment(segments, video["title"], cfg["find"], cfg)
        print(f"[find] '{cfg['find']}': {'found' if picks else 'not in this part'}")
        cfg = {**cfg, "min_score": 0}
        src = {**src, "require_game": ""}
    else:
        picks = pick_clips(segments, video["title"], cfg, spikes)
    clips = snap_to_words(picks, all_words(segments), cfg)
    clips.sort(key=lambda c: -c["score"])
    weak = [c for c in clips if c.get("score", 10) < cfg["min_score"]]
    clips = [c for c in clips if c.get("score", 10) >= cfg["min_score"]]
    if weak:
        print(f"[select] dropped {len(weak)} weak moment(s) scoring under {cfg['min_score']}")
    is_part = video.get("parts", 1) > 1 or bool(video.get("part"))
    cap = cfg["stream_clips_per_hour"] if is_part else cfg["max_clips_per_video"]
    if len(clips) > 2 and not cfg.get("find"):
        from .highlights import rerank
        clips = rerank(clips, cfg)  # best first, judged against each other
    if src.get("require_game"):
        # campaign only pays for this game: drop IRL / chatting / other-game moments
        from .gamecheck import shows_game
        kept = []
        for c in clips:
            if len(kept) >= cap:
                break
            ok, what = shows_game(video["path"], c["start"], c["end"], src["require_game"], cfg)
            if ok:
                kept.append(c)
            else:
                print(f"[gamecheck] dropped '{c['title']}': not {src['require_game']} ({what})")
        clips = kept
    clips = [apply_campaign(c, src) for c in clips[:cap]]
    print(f"[select] {len(picks)} suggested, {len(clips)} kept")

    manifest = []
    for i, clip in enumerate(clips, 1):
        name = f"clip_{i:02d}_{slugify(clip['title'], 40)}.mp4"
        layout = render_clip(video["path"], clip, out_dir / name, cfg, overlay=src.get("overlay"),
                             webcam=src.get("webcam"), gameplay_only=bool(src.get("require_game")))
        text = post_text(clip)
        (out_dir / name).with_suffix(".txt").write_text(f"{clip['title']}\n\n{text}\n")
        print(f"[render] {name} ({clip['end'] - clip['start']:.0f}s, {layout}, score {clip['score']})")
        manifest.append({k: v for k, v in clip.items() if k != "words"} | {"file": name, "layout": layout})

    # Number every batch (and every clip in it) so they're easy to talk about:
    # "Batch 4", clip "4.2".
    batch = next_batch() if (next_batch and manifest) else None
    label = batch_label(video, src)
    head_title = f"Batch {batch} · {label}" if batch else label
    for i, m in enumerate(manifest, 1):
        m["id"] = f"{batch}.{i}" if batch else str(i)
        (out_dir / m["file"]).with_suffix(".txt").write_text(
            f"Clip {m['id']} · score {m['score']}/10\n{m['title']}\n\n{post_text(m)}\n")

    (out_dir / "manifest.json").write_text(json.dumps(
        {"source": video.get("url") or str(video["path"]), "title": head_title,
         "batch": batch, "video_title": video["title"], "clips": manifest}, indent=2))

    if record and manifest:
        record([{"id": m["id"], "title": m["title"], "score": m["score"],
                 "streamer": src.get("name") or "", "at": int(time.time())} for m in manifest])

    if deliver.telegram_enabled() and manifest:
        head = f"📦 {head_title} · {len(manifest)} clips\n{video['title']}"
        if src.get("reminder"):
            head += f"\n\n📌 {src['reminder']}"
        deliver.send_message(head)
        for m in manifest:
            deliver.send_clip(out_dir / m["file"],
                              f"📦 {m['id']} · ⭐ {m['score']}/10\n{m['title']}\n\n{post_text(m)}")
    return out_dir


def _local_now(cfg: dict) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=cfg["utc_offset_hours"])


def _pick_lines(clips: list) -> str:
    return "\n".join(f"• {c['id']}  ⭐{c['score']}  {c['streamer']}: {c['title']}" for c in clips)


def daily_top_picks(state: dict, cfg: dict) -> None:
    """Once a day (after digest_hour, your local time) send the best clips of the
    last 36 h that haven't been suggested yet, so you know exactly what to post."""
    now = _local_now(cfg)
    today = f"{now:%Y-%m-%d}"
    if now.hour < cfg["digest_hour"] or state.get("last_digest") == today:
        return
    cutoff = time.time() - 36 * 3600
    fresh = [c for c in state.get("clips", []) if c["at"] >= cutoff and not c.get("suggested")]
    if not fresh:
        return
    top = sorted(fresh, key=lambda c: (-c["score"], -c["at"]))[: cfg["digest_count"]]
    for c in top:
        c["suggested"] = today
    state["last_digest"] = today
    if deliver.telegram_enabled():
        deliver.send_message(f"📌 Today's top {len(top)} to post (best first):\n\n{_pick_lines(top)}\n\n"
                             "Post each to TikTok + YouTube + Instagram, then submit the links.")
    print(f"[digest] sent today's top {len(top)}")


def finish_single_stream(state: dict, src: dict) -> None:
    """A one-off stream (single_stream: true, e.g. a 24h marathon) has ended and every
    part is clipped: stop watching that channel and send the best of it."""
    if not src.get("single_stream") or src["url"] in state.get("finished_sources", {}):
        return
    state.setdefault("finished_sources", {})[src["url"]] = f"{dt.date.today()}"
    print(f"[done] {src.get('name') or src['url']}: stream fully clipped, no longer watching")
    final_summary(state, src)


def final_summary(state: dict, src: dict) -> None:
    """When a one-off stream (e.g. a 24h marathon) is fully clipped, send the best of it."""
    name = src.get("name") or ""
    mine = [c for c in state.get("clips", []) if c.get("streamer") == name]
    if not mine or not deliver.telegram_enabled():
        return
    best = sorted(mine, key=lambda c: -c["score"])[:10]
    deliver.send_message(f"🏁 {name} stream finished and fully clipped: {len(mine)} clips.\n"
                         f"Best 10:\n\n{_pick_lines(best)}\n\nNo longer watching {name}.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    lv = sub.add_parser("live")
    lv.add_argument("--start-at", type=float, default=None,
                    help="continue a recording from this UTC timestamp (hand-off between runs)")
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
        if args.cmd == "live":
            todo = []
        elif args.cmd == "run":
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
            # "parts=2-13" among the links = re-make just those hours of a long stream
            # (doesn't touch the live progress, so it can run next to the hourly runs)
            remake = next((u for u in args.urls if u.startswith("parts=")), None)
            find = next((u for u in args.urls if u.startswith("find=")), None)
            if find:  # find=fixing_a_pipe_lady_walks_in -> look for that one moment
                cfg["find"] = find[5:].replace("_", " ")
            urls = [u for u in args.urls if not u.startswith(("parts=", "find="))]
            if remake:
                remake_urls, urls = urls, []
            todo = [{"id": None, "url": u, "duration": 0, **({"source": forced} if forced else {})}
                    for u in urls]

        # GitHub stops a job after 6h. RUN_BUDGET_MINUTES (set by the workflow) makes
        # us leave a video for the next run instead of getting killed halfway through.
        budget = float(os.environ.get("RUN_BUDGET_MINUTES") or 0) * 60
        started = time.time()
        part_secs = cfg["stream_part_hours"] * 3600

        def next_batch() -> int:
            state["batch_counter"] = state.get("batch_counter", 0) + 1
            fetch.save_state(state)
            return state["batch_counter"]

        def record(entries: list) -> None:
            state.setdefault("clips", []).extend(entries)
            fetch.save_state(state)

        if args.cmd == "live":
            from .live import record_and_clip
            done += record_and_clip(cfg, args.start_at, process_video, next_batch, record, state)

        if args.cmd == "url" and remake:
            lo, _, hi = remake[6:].partition("-")
            for u in remake_urls:
                src = forced or fetch.find_source(cfg, u)
                for p in range(int(lo) - 1, int(hi or lo)):
                    try:
                        video = fetch.download(u, work, cfg, p, src)
                        video["source"] = src
                        done.append(process_video(video, cfg, next_batch=next_batch, record=record))
                    except (fetch.NotReady, fetch.Skip) as e:
                        print(f"[remake] hour {p + 1}: {e}")
                        break
                    except Exception as e:
                        print(f"[remake] hour {p + 1} failed: {e}")
                    finally:
                        shutil.rmtree(work, ignore_errors=True)
                        fetch.save_state(state)

        for item in todo:
            url = item["url"]
            key = item["id"] or url
            try:
                if not item["id"]:  # a URL run by hand: look up its id to resume parts
                    item["id"] = fetch.probe_url(url)["id"]
                # Long streams come in parts; keep going while there's time in this run.
                seen_parts = set()
                while True:
                    est = min(item["duration"] or part_secs, part_secs) * cfg["processing_ratio"] + 15 * 60
                    if budget and done and time.time() - started + est > budget:
                        print(f"[later] not enough time left for {url}, next run will take it")
                        break
                    part = state["partial"].get(item["id"], 0)
                    if part in seen_parts:  # safety net: progress must move forward
                        print(f"[error] {url}: part {part + 1} came up twice, stopping this video")
                        break
                    seen_parts.add(part)
                    src = item.get("source") or fetch.find_source(cfg, url)
                    video = fetch.download(url, work, cfg, part, src)
                    if item.get("source", {}).get("name") or item.get("source", {}).get("notes"):
                        video["source"] = item["source"]
                    out = process_video(video, cfg, next_batch=next_batch, record=record)
                    shutil.rmtree(work, ignore_errors=True)
                    done.append(out)
                    state["failures"].pop(key, None)
                    if video["part"] + 1 < video["parts"]:
                        state["partial"][item["id"]] = video["part"] + 1
                        state["partial_urls"][item["id"]] = url
                        fetch.save_state(state)
                        continue  # next part (or NotReady if it's still being streamed)
                    state["partial"].pop(item["id"], None)
                    state["partial_urls"].pop(item["id"], None)
                    state["processed"][item["id"]] = {
                        "title": video["title"], "date": f"{dt.date.today()}",
                        "output": str(out.relative_to(ROOT)) if out else None}
                    if video.get("parts", 1) > 1 or video.get("part"):
                        finish_single_stream(state, src)
                    break
            except fetch.NotReady as e:
                print(f"[later] {url}: {e}")
            except TimeoutError as e:  # stuck download: retry next run, don't give up on it
                print(f"[later] {url}: {e}")
            except fetch.Skip as e:
                print(f"[skip] {url}: {e}")
                if "all parts already clipped" in str(e):  # stream ended right after a part
                    state["partial"].pop(item["id"], None)
                    state["partial_urls"].pop(item["id"], None)
                    finish_single_stream(state, item.get("source") or fetch.find_source(cfg, url))
                if item["id"]:
                    state["processed"][item["id"]] = {"date": f"{dt.date.today()}", "skipped": str(e)}
            except Exception as e:
                print(f"[error] {url}: {e}")
                n = state["failures"][key] = state["failures"].get(key, 0) + 1
                if n >= 3 and item["id"]:  # stop retrying a video that keeps failing
                    state["processed"][item["id"]] = {"date": f"{dt.date.today()}", "error": str(e)[:300]}
                    state["partial"].pop(item["id"], None)  # stop retrying it in later runs
                    state["partial_urls"].pop(item["id"], None)
                if deliver.telegram_enabled():
                    deliver.send_message(f"⚠️ Clipper failed on {url} (try {n}/3): {str(e)[:300]}")
            finally:
                fetch.save_state(state)  # save after each video so progress isn't lost
                shutil.rmtree(work, ignore_errors=True)

        try:
            daily_top_picks(state, cfg)
        except Exception as e:  # never fail a run over the digest
            print(f"[digest] skipped: {e}")
        fetch.save_state(state)

    done = [d for d in done if d]
    # GitHub Actions reads this to publish releases
    (ROOT / ".last_run.json").write_text(json.dumps([str(d) for d in done]))
    print(f"\nDone. {len(done)} video(s) clipped.")


if __name__ == "__main__":
    main()
