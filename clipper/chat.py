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
    MOODS.clear()
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
                    msg = " ".join(f.get("text") or "" for f in frags)
                    if is_nomination(msg):
                        NOMINATIONS[b] = NOMINATIONS.get(b, 0) + 1
                    mood = message_mood(msg)
                    if mood:
                        MOODS.setdefault(b, {})[mood] = MOODS.setdefault(b, {}).get(mood, 0) + 1
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
        if s["chat"] >= 5:  # a real reaction: say what kind (laughing, hyped...)
            moods: dict[str, int] = {}
            for b in range(a, int(s["end"]) + 20, BUCKET):
                for m, n in MOODS.get(b, {}).items():
                    moods[m] = moods.get(m, 0) + n
            if moods and max(moods.values()) >= 3:
                s["chat_mood"] = max(moods, key=moods.get)
    spikes = sorted(({"t": b, "rate": n, "x": round(n / median, 1)} for b, n in counts.items()
                     if n >= 2 * median and n >= 5), key=lambda d: -d["rate"])[:15]
    return sorted(spikes, key=lambda d: d["t"])


# ---------------------------------------------------------------------------
# Live chat (read while recording). Twitch lets anyone read a channel's chat
# anonymously over IRC, so no login or key is needed.

# What chat's reaction says about the moment (idea from stream-clipping tools:
# a wall of KEKW is a funny moment, POG a big play, monkaS a scare...).
MOOD_WORDS = {
    "laughing": {"lul", "lulw", "kekw", "omegalul", "icant", "kek", "lol", "lmao", "lmfao", "xd",
                 "pepelaugh", "4head", "haha", "hahaha", "😂", "🤣", "💀"},
    "hyped": {"pog", "poggers", "pogu", "pogchamp", "letsgo", "letsgooo", "insane", "holy", "clutch",
              "w", "ww", "gigachad", "omg", "wow", "goat", "🔥", "😱", "🤯", "🐐"},
    "shocked": {"huh", "what", "wtf", "?!", "!?", "😮", "😳", "nah"},
    "scared": {"monkas", "monkaw", "aaaa", "jumpscare", "😨", "😰"},
    "fail": {"f", "l", "rip", "sadge", "noooo", "threw", "😭", "💔"},
}
MOODS: dict[int, dict[str, int]] = {}


def message_mood(text: str) -> str | None:
    words = re.findall(r"[\w']+|[?!]{2,}|[^\w\s?!]", text.casefold())
    best, hits = None, 0
    for mood, vocab in MOOD_WORDS.items():
        n = sum(1 for w in words if w in vocab)
        if n > hits:
            best, hits = mood, n
    return best


class LiveChat:
    """Logs a channel's chat to a file as "<unix time>\\t<message>" lines, in a
    background thread, reconnecting if the connection drops."""

    def __init__(self, channel: str, path):
        import threading
        self.channel, self.path = channel.lower().lstrip("#"), path
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.count = 0

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()

    def _run(self):
        import socket
        import ssl
        backoff = 5
        while not self.stop_event.is_set():
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=30)
                sock = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
                sock.settimeout(360)
                nick = f"justinfan{int(time.time()) % 100000}"
                sock.sendall(f"NICK {nick}\r\nJOIN #{self.channel}\r\n".encode())
                print(f"[chat] reading #{self.channel} live chat")
                backoff, buf = 5, b""
                with open(self.path, "a", encoding="utf-8") as out:
                    while not self.stop_event.is_set():
                        data = sock.recv(65536)
                        if not data:
                            raise ConnectionError("chat connection closed")
                        buf += data
                        *lines, buf = buf.split(b"\r\n")
                        for line in lines:
                            text = line.decode("utf-8", "replace")
                            if text.startswith("PING"):
                                sock.sendall(("PONG" + text[4:] + "\r\n").encode())
                            elif " PRIVMSG #" in text:
                                msg = text.split(" :", 1)[1] if " :" in text else ""
                                out.write(f"{time.time():.1f}\t{msg.replace(chr(9), ' ')}\n")
                                self.count += 1
                        out.flush()
            except Exception as e:
                if self.stop_event.is_set():
                    break
                print(f"[chat] live chat dropped ({e}), reconnecting in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)


def live_counts(path, start_epoch: float, end_epoch: float) -> dict[int, int] | None:
    """Like chat_counts, but from a live chat log: messages per 10 s bucket of the
    video that starts at start_epoch. Fills NOMINATIONS and MOODS too."""
    NOMINATIONS.clear()
    MOODS.clear()
    counts: dict[int, int] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t, _, msg = line.rstrip("\n").partition("\t")
                try:
                    t = float(t)
                except ValueError:
                    continue
                if not (start_epoch <= t < end_epoch):
                    continue
                b = int((t - start_epoch) // BUCKET) * BUCKET
                counts[b] = counts.get(b, 0) + 1
                if is_nomination(msg):
                    NOMINATIONS[b] = NOMINATIONS.get(b, 0) + 1
                mood = message_mood(msg)
                if mood:
                    MOODS.setdefault(b, {})[mood] = MOODS.setdefault(b, {}).get(mood, 0) + 1
    except FileNotFoundError:
        return None
    total = sum(counts.values())
    print(f"[chat] {total} live chat messages in this part")
    return counts if total >= 30 else None
