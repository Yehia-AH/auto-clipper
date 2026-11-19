"""Ask Claude to pick the most clippable moments from a transcript."""
import json

import anthropic

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "Start time in seconds"},
                    "end": {"type": "number", "description": "End time in seconds"},
                    "title": {"type": "string", "description": "Short on-video hook title, max 8 words"},
                    "caption": {"type": "string", "description": "Post caption, 1-2 sentences, no hashtags"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "integer", "description": "Viral potential 1-10"},
                    "why": {"type": "string", "description": "One line on why this moment works"},
                },
                "required": ["start", "end", "title", "caption", "hashtags", "score", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM = """You are an expert short-form video editor who picks the moments from \
long videos that will perform best as standalone TikTok / YouTube Shorts / Reels clips.

A great clip:
- Opens on a hook: the first sentence grabs attention on its own (a bold claim, \
question, surprising fact, or the start of a story). Never start mid-sentence or \
on filler like "so", "yeah", "um", "and".
- Is self-contained: makes sense to someone who has not seen the rest of the video.
- Has a payoff: ends on a punchline, conclusion, or strong line. Never cut off \
mid-thought.
- Has no dead air or long tangents.

Each transcript line may show "(energy N)": how loud the audio gets on that line \
compared with the rest of the video, 0 (quietest) to 10 (loudest). For gaming and \
stream content, energy spikes (yelling, laughing, hype, rage) are the strongest sign \
of a clip-worthy moment: a great stream clip almost always has an energy spike in the \
first few seconds or at the payoff. Do not pick calm, low-energy talk unless the line \
itself is genuinely funny or shocking without any visuals. You only have the \
transcript, so prefer moments where the speech itself makes clear something exciting \
just happened.

Lines may also show "(chat N)": how hard Twitch chat reacted right after that line, \
0-10 (3 = normal, 6 = double the usual rate, 9-10 = chat exploded). Chat reacts 5-20 \
seconds AFTER the moment happens, so a chat spike is the strongest signal of all that \
something clip-worthy just happened. When there is a big chat spike, build the clip \
around it: start about 15-20 seconds BEFORE the spike so the viewer gets the setup, \
and end just after the reaction / punchline. A moment with both high energy and high \
chat is almost always the best clip available.

Lines may show '(Nx "clip it" in chat)': viewers literally asking for that moment to \
be clipped. Treat that as a direct vote for the moment.

Lines may show "(event: ...)": the streamer clearly describes something happening right \
now (chase, crash, stunt, combat, npc_chaos, funny_dialogue, reaction, milestone). \
These are strong candidates, especially combined with high energy or chat. The setup \
usually comes right before the line, so start the clip a little earlier.

Use the timestamps in the transcript exactly: a clip's start must be the start time \
of the line it opens on, and its end must be the end time of the line it closes on. \
Clips must not overlap. Sort clips by score, best first."""


def _format_transcript(segments: list[dict]) -> str:
    return "\n".join(
        f"[{s['start']:.2f}-{s['end']:.2f}]"
        + (f" (energy {s['energy']})" if "energy" in s else "")
        + (f" (chat {s['chat']})" if "chat" in s else "")
        + (f" ({s['clip_it']}x \"clip it\" in chat)" if s.get("clip_it") else "")
        + (f" (event: {', '.join(s['cues'])})" if s.get("cues") else "")
        + f" {s['text']}" for s in segments)


def _hms(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}"


def _spike_note(spikes: list[dict], a: float, b: float) -> str:
    inside = [x for x in spikes if a <= x["t"] < b]
    if not inside:
        return ""
    lines = ", ".join(f"{_hms(x['t'])} ({x['x']}x normal)" for x in inside)
    return f"Biggest chat spikes in this section: {lines}.\n\n"


def pick_clips(segments: list[dict], title: str, cfg: dict, spikes: list | None = None) -> list[dict]:
    """Short videos: one request. Long streams: one request per ~hour of footage,
    so moments deep into a stream get the same attention as the start."""
    total = segments[-1]["end"]
    if total <= cfg["long_video_minutes"] * 60:
        return _ask(segments, title, cfg["clips_per_video"],
                    _spike_note(spikes or [], 0, total + 1), cfg)

    window = 60 * 60
    chunks, cur, cur_start = [], [], segments[0]["start"]
    for s in segments:
        if cur and s["start"] - cur_start > window:
            chunks.append(cur)
            cur, cur_start = [], s["start"]
        cur.append(s)
    if cur:
        chunks.append(cur)

    picks = []
    for i, chunk in enumerate(chunks, 1):
        hours = max((chunk[-1]["end"] - chunk[0]["start"]) / 3600, 0.25)
        n = max(1, round(cfg["stream_clips_per_hour"] * hours))
        note = (f"This is part {i} of {len(chunks)} of a live stream VOD "
                f"({_hms(chunk[0]['start'])} to {_hms(chunk[-1]['end'])}). Streams have "
                "downtime, chatter with chat, and loading screens: skip those, only pick "
                "moments that work for someone who never watched the stream.\n\n")
        note += _spike_note(spikes or [], chunk[0]["start"], chunk[-1]["end"] + 20)
        got = _ask(chunk, title, n, note, cfg)
        print(f"[select] part {i}/{len(chunks)}: {len(got)} moments")
        picks.extend(got)
    return picks


def _ask(segments: list[dict], title: str, n: int, note: str, cfg: dict) -> list[dict]:
    client = anthropic.Anthropic()
    prompt = (
        f"Video title: {title}\n\n"
        f"Audience notes: {cfg['niche_notes']}\n\n"
        f"{note}"
        f"Pick up to {n} clips, each between "
        f"{cfg['min_clip_seconds']} and {cfg['max_clip_seconds']} seconds long. "
        "Fewer is fine if the video doesn't have that many strong moments. "
        "Write titles, captions and hashtags in the language of the video.\n\n"
        f"<transcript>\n{_format_transcript(segments)}\n</transcript>"
    )
    request = dict(
        model=cfg["model"],
        max_tokens=16000,
        system=SYSTEM,
        output_config={
            "effort": cfg["effort"],
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        messages=[{"role": "user", "content": prompt}],
    )
    if cfg["model"].startswith("claude-haiku"):
        # Haiku has no server-side fallback model
        response = client.messages.create(**request)
    else:
        response = client.beta.messages.create(
            **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if response.stop_reason == "refusal":
        print(f"[select] model declined this video: {response.stop_details}")
        return []
    if response.stop_reason == "max_tokens":
        raise RuntimeError("clip selection hit max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["clips"]


def snap_to_words(clips: list[dict], words: list[dict], cfg: dict) -> list[dict]:
    """Align each clip to real word boundaries and enforce length limits."""
    result = []
    for c in sorted(clips, key=lambda c: -c.get("score", 0)):  # best first wins overlaps
        inside = [w for w in words if w["start"] >= c["start"] - 0.3 and w["end"] <= c["end"] + 0.5]
        if not inside:
            continue
        start = max(0.0, inside[0]["start"] - 0.15)
        # trim from the end (at word boundaries) if too long
        while inside and inside[-1]["end"] - start > cfg["max_clip_seconds"]:
            inside.pop()
        if not inside:
            continue
        end = inside[-1]["end"] + 0.35
        if end - start < cfg["min_clip_seconds"] * 0.8:
            continue
        if any(start < r["end"] and end > r["start"] for r in result):
            continue  # overlaps a better clip
        result.append({**c, "start": round(start, 2), "end": round(end, 2), "words": inside})
    return result


def find_moment(segments: list[dict], title: str, description: str, cfg: dict) -> list[dict]:
    """Find one specific moment the user described (returns [] if it isn't here)."""
    note = (f"The user is looking for ONE specific moment: \"{description}\". Return exactly "
            "that moment as a single clip if it happens in this transcript, with the setup "
            "before it and the reaction after it. If it is not in this transcript, return an "
            "empty list of clips. Ignore the usual audience notes; only this moment matters.\n\n")
    return _ask(segments, title, 1, note, {**cfg, "max_clip_seconds": max(cfg["max_clip_seconds"], 60)})
