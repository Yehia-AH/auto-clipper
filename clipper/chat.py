"""Twitch chat activity for a VOD: chat explodes a few seconds after something
clip-worthy happens, so message spikes are the best "this moment hit" signal.

Uses the same public chat-replay API the Twitch website uses. If Twitch refuses,
everything still works without the chat signal."""
import re
import time

import requests

GQL = "https://gql.twitch.tv/gql"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch's public web client id
BUCKET = 10  # seconds
PERSISTED_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"


RAW_QUERY = """query($id: ID!, $offset: Int, $cursor: Cursor) {
  video(id: $id) {
    comments(contentOffsetSeconds: $offset, after: $cursor) {
      edges { cursor node { contentOffsetSeconds message { fragments { text } } } }
      pageInfo { hasNextPage }
    }
  }
}"""
_mode = {"raw": False}


def _page(session, vod_id: str, offset: int | None, cursor: str | None) -> dict:
    try:
        return _request(session, vod_id, offset, cursor, raw=_mode["raw"])
    except RuntimeError:
        if _mode["raw"]:
            raise
        _mode["raw"] = True  # persisted query hash rejected: try the plain query
        return _request(session, vod_id, offset, cursor, raw=True)


def _request(session, vod_id: str, offset: int | None, cursor: str | None, raw: bool) -> dict:
    if raw:
        body = {"query": RAW_QUERY,
                "variables": {"id": vod_id, "offset": None if cursor else (offset or 0),
                              "cursor": cursor}}
    else:
        variables = {"videoID": vod_id}
        if cursor:
            variables["cursor"] = cursor
        else:
            variables["contentOffsetSeconds"] = offset or 0
        body = {"operationName": "VideoCommentsByOffsetOrCursor", "variables": variables,
                "extensions": {"persistedQuery": {"version": 1, "sha256Hash": PERSISTED_HASH}}}
    r = session.post(GQL, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        data = data[0]
    if data.get("errors"):
        raise RuntimeError(str(data["errors"])[:200])
    comments = ((data.get("data") or {}).get("video") or {}).get("comments")
    if comments is None:
        raise RuntimeError("no comments field in response")
    return comments


_NOMINATION = re.compile(r"\b(?:clip (?:that|this|it)|clip it|clipworthy|clip worthy|clippp+|save (?:that|this))\b")
_NO_NOMINATION = re.compile(r"\b(?:don'?t|do not|never|not|no need to)\b")


def is_nomination(text: str) -> bool:
    """A viewer asking for a clip ("clip that", "clip it"). Pattern adapted from
    ColinGPT9's GTA Clips Kitty plugin (MIT)."""
    t = text.casefold().replace("\u2019", "'")
    for clause in re.split(r"[.!?;\n]|\bbut\b", t):
        m = _NOMINATION.search(clause)
        if m and not _NO_NOMINATION.search(clause[:m.end()]):
            return True
    return False


NOMINATIONS: dict[int, int] = {}


def chat_counts(vod_id: str, start: float, end: float, max_seconds: float = 240) -> dict[int, int] | None:
    """Messages per 10 s bucket between start and end (VOD seconds), keyed by the
    bucket's start relative to `start`. None if chat replay isn't available.
    "Clip it" nominations per bucket are left in NOMINATIONS."""
    NOMINATIONS.clear()
    vod_id = str(vod_id).lstrip("v")
    s = requests.Session()
    s.headers.update({"Client-Id": CLIENT_ID, "Content-Type": "text/plain;charset=UTF-8"})
    counts: dict[int, int] = {}
    cursor, t0, pages = None, time.time(), 0
    try:
        while True:
            c = _page(s, vod_id, int(start) if not cursor else None, cursor)
            pages += 1
            edges = c.get("edges") or []
            last_off = start
            for e in edges:
                off = (e.get("node") or {}).get("contentOffsetSeconds")
                if off is None:
                    continue
                last_off = off
                if start <= off < end:
                    b = int((off - start) // BUCKET) * BUCKET
                    counts[b] = counts.get(b, 0) + 1
                    frags = (((e.get("node") or {}).get("message") or {}).get("fragments") or [])
                    if is_nomination(" ".join(f.get("text") or "" for f in frags)):
                        NOMINATIONS[b] = NOMINATIONS.get(b, 0) + 1
            if last_off >= end or not (c.get("pageInfo") or {}).get("hasNextPage") or not edges:
                break
            cursor = edges[-1].get("cursor")
            if not cursor or time.time() - t0 > max_seconds:
                break
    except Exception as e:
        print(f"[chat] chat replay unavailable: {e}")
        return None
    total = sum(counts.values())
    print(f"[chat] {total} messages in {pages} pages ({time.time() - t0:.0f}s)")
    return counts if total else None


def add_chat(segments: list[dict], counts: dict[int, int]) -> list[dict]:
    """Tag each segment with chat hype 0-10: the busiest 10 s of chat in the 20 s
    after the line (chat reacts late), relative to the typical rate. Returns the
    top spikes as [{t, rate, x}] for the prompt."""
    if not counts:
        return []
    rates = sorted(counts.values())
    median = max(rates[len(rates) // 2], 1)
    for s in segments:
        a = int(s["start"] // BUCKET) * BUCKET
        window = [counts.get(b, 0) for b in range(a, int(s["end"]) + 20, BUCKET)]
        peak = max(window) if window else 0
        ratio = peak / median
        # 1x typical -> ~3, 2x -> ~6, 3x+ -> ~9-10
        s["chat"] = max(0, min(10, round(3 * ratio)))
        noms = sum(NOMINATIONS.get(b, 0) for b in range(a, int(s["end"]) + 20, BUCKET))
        if noms:
            s["clip_it"] = noms
    spikes = sorted(({"t": b, "rate": n, "x": round(n / median, 1)} for b, n in counts.items()
                     if n >= 2 * median and n >= 5), key=lambda d: -d["rate"])[:15]
    return sorted(spikes, key=lambda d: d["t"])
