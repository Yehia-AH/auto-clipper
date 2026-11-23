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
                    "title": {"type": "string", "description": "On-screen hook text, 3-8 words: a teaser that makes people keep watching, not a description"},
                    "caption": {"type": "string", "description": "Post caption for TikTok/Reels/Shorts: punchy hook, not a description. No hashtags"},
                    "x_caption": {"type": "string", "description": "Caption for X/Twitter: one short punchy line, max 120 characters, no hashtags"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "integer", "description": "Viral potential 1-10"},
                    "why": {"type": "string", "description": "One line on why this moment works"},
                },
                "required": ["start", "end", "title", "caption", "x_caption", "hashtags", "score", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM = """You are an expert short-form video editor who picks the moments from \
long streams that will go viral as standalone TikTok / YouTube Shorts / Reels clips.

Anything that makes someone stop scrolling and watch to the end counts. Look for all of \
these, not just talking:
- Crazy gameplay: a wild stunt, chase, crash, explosion, close call, glitch, chaotic NPC, \
a fail, an insane play.
- Big reactions: freakouts, screaming, disbelief, rage, laughing fits, jump scares.
- Discoveries in the game: glitches and bugs, easter eggs, secrets, hidden details, \
weird physics, a mechanic or feature he didn't know about, "wait, you can do THAT?", \
"no way this is in the game". New-game discoveries get huge views: rank them high, and \
start the clip just before he notices so viewers see it with him.
- Chat moments: chat explodes, roasts him, or he reacts to something chat said.
- The streamer himself: a funny bit, a hot take, a story, a roast, a relatable or \
wholesome moment, his personality.
The best clips combine two: crazy gameplay AND a big reaction, or a funny line AND chat \
exploding.

Lines like "[no talking: very loud game moment]" mark loud gameplay where nobody speaks \
(crash, explosion, gunfight, chase). The reaction usually comes right after it: a clip \
that starts a few seconds before such a line and ends after the reaction is often great.

Harsh rubric: a clip must pass ALL four, or it is not a clip.
1. Works with zero context. A stranger scrolling understands it. No "what happened 10 \
minutes ago", inside jokes, or game state they can't see.
2. Strong first 1-2 seconds. Start on the line or the reaction itself. Never start on \
filler ("so", "yeah", "um", "okay so", "anyway", "and").
3. A payoff: a big reaction (freakout, disbelief, scream, laughing fit), a fail, a \
discovery ("wait, is that...?"), a hot take, a funny line. End right after it (the laugh \
or 1-2 s of reaction), never on the next topic and never mid-thought.
4. Let the moment set the length: a punchy one-liner can be 15 s, a story that builds to \
a payoff 45-60 s. 20-40 s is the sweet spot.

Score 1-10 for viral potential, and be critical: most moments are 5-6. 9-10 = viral on \
its own; 7-8 = strong, worth posting; 5-6 = fine; below 5 = not a clip. Minus 2 if it \
needs context, minus 2 for a slow first second, minus 3 if nothing happens at the end. \
Boost moments that name or react to another streamer, creator or celebrity, or drama \
and hot topics: they ride existing attention. Prefer variety: different kinds of moments, \
spread across the video.

Also skip: words that aren't the streamer's (game characters, cutscenes, a video he is \
watching) with no reaction from him; long stretches of chatting to chat; anything about \
politics, tragedy, slurs, or sexual comments about real people.

Each transcript line may show "(energy N)": how loud the audio gets on that line \
compared with the rest of the video, 0 (quietest) to 10 (loudest). For gaming and \
stream content, energy spikes (yelling, laughing, hype, rage) are a strong sign of a \
clip-worthy moment: a great stream clip almost always has an energy spike in the first \
few seconds or at the payoff. A mild-sounding line right at a big spike is often a great \
clip. You only have the transcript, so prefer moments where the speech itself makes \
clear something exciting just happened.

Lines may also show "(chat N)": how hard Twitch chat reacted right after that line, \
0-10 (3 = normal, 6 = double the usual rate, 9-10 = chat exploded), and sometimes \
"(chat: laughing / hyped / shocked / scared / fail)": what chat's messages said. Chat \
reacts 5-20 seconds AFTER the moment, so a chat spike is the strongest signal of all \
that something clip-worthy just happened. When there is a big chat spike, build the clip \
around it: start about 15-20 seconds BEFORE the spike so the viewer gets the setup, and \
end just after the reaction / punchline. A moment with both high energy and high chat is \
almost always the best clip available.

Lines may show '(Nx "clip it" in chat)': viewers literally asking for that moment to \
be clipped. Treat that as a direct vote for the moment.

Lines may show "(event: ...)": the streamer clearly describes something happening right \
now (chase, crash, stunt, combat, npc_chaos, funny_dialogue, reaction, milestone, discovery = a glitch / easter egg / hidden detail). \
These are strong candidates, especially combined with high energy or chat. The setup \
usually comes right before the line, so start the clip a little earlier.

Use the timestamps in the transcript exactly: a clip's start must be the start time \
of the line it opens on, and its end must be the end time of the line it closes on. \
Clips must not overlap. Sort clips by score, best first.

The title is the on-screen hook shown on the video: 3-8 words that make people keep \
watching, in the same teasing style as the captions, never a plain description. Bad: \
"Clix frees a polar bear". Good: "he did NOT think this through" / "wait for the bear..." \
/ "nobody expected this". No emoji in the title (the video font can't draw them). \
Base it on what really happens in the clip (never invent events) and don't spoil the \
payoff. The \
caption is 1-2 short sentences and may end with an easy question to get comments.

Captions must make people NEED to watch, never explain or summarise the clip. Bad (an \
explanation): "Clix frees a polar bear in GTA 6 and it attacks someone." Good (a hook): \
"he really thought this was a good idea 💀" / "nobody was ready for what the bear did" / \
"this is why you don't trust Clix with animals". Write like a fan reposting a clip: \
short, lowercase is fine, tease the payoff without giving it away, quote the funniest \
line he says, ask a hot question, or use a relatable reaction. 1-2 emoji max. The \
x_caption is the same idea in one line for X/Twitter (max 120 characters). Name the \
streamer naturally in both when it fits ("Clix really thought..."), since campaigns \
require it."""


def _format_transcript(segments: list[dict]) -> str:
    return "\n".join(
        f"[{s['start']:.2f}-{s['end']:.2f}]"
        + (f" (energy {s['energy']})" if "energy" in s else "")
        + (f" (chat {s['chat']})" if "chat" in s else "")
        + (f" (chat: {s['chat_mood']})" if s.get("chat_mood") else "")
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
        if 1.0 < inside[0]["start"] - c["start"] <= 10:
            start = max(0.0, c["start"])  # opens on gameplay before anyone speaks: keep it
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


ORDER_SCHEMA = {
    "type": "object",
    "properties": {"order": {"type": "array", "items": {"type": "integer"}}},
    "required": ["order"],
    "additionalProperties": False,
}


def rerank(clips: list[dict], cfg: dict) -> list[dict]:
    """Order candidates against each other (relative judgment is more reliable than
    each clip's own score, which tends to cluster at 7-9). Keeps all clips."""
    if len(clips) < 3:
        return clips
    lines = []
    for i, c in enumerate(clips):
        words = " ".join(w["word"].strip() for w in c.get("words", []))[:900]
        lines.append(f"[{i}] {c['end'] - c['start']:.0f}s, score {c['score']}, "
                     f"title: {c['title']}\n    spoken: {words}")
    prompt = (f"Below are {len(clips)} candidate clips from one stream. Order ALL of them from "
              "MOST likely to go viral as a TikTok/Short to LEAST. Judge them against each other: "
              "hook strength in the first 2 seconds, emotional intensity, payoff, quotability, "
              "and whether it works with zero context. List every index exactly once.\n\n"
              + "\n".join(lines))
    try:
        client = anthropic.Anthropic()
        # ranking a handful of short candidates: the cheap check model is plenty
        rank_model = cfg.get("check_model") or cfg["model"]
        request = dict(model=rank_model, max_tokens=2000,
                       output_config={"effort": "low",
                                      "format": {"type": "json_schema", "schema": ORDER_SCHEMA}},
                       messages=[{"role": "user", "content": prompt}])
        response = client.messages.create(**request)
        text = next(b.text for b in response.content if b.type == "text")
        order = [i for i in json.loads(text)["order"] if isinstance(i, int) and 0 <= i < len(clips)]
        seen, ranked = set(), []
        for i in order + list(range(len(clips))):
            if i not in seen:
                seen.add(i)
                ranked.append(clips[i])
        print("[rerank] " + " > ".join(c["title"][:30] for c in ranked))
        return ranked
    except Exception as e:  # ranking is a bonus; keep the score order if it fails
        print(f"[rerank] skipped: {e}")
        return clips
