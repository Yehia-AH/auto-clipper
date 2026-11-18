"""Check that a clip actually shows a given game (e.g. GTA 6) before it's made:
Claude looks at 3 frames from the clip. Used for campaigns that only pay for
gameplay, so IRL / just-chatting / other-game moments get dropped."""
import base64
import json
from pathlib import Path

import anthropic
import cv2

SCHEMA = {
    "type": "object",
    "properties": {
        "shows_game": {"type": "boolean"},
        "what_is_on_screen": {"type": "string"},
    },
    "required": ["shows_game", "what_is_on_screen"],
    "additionalProperties": False,
}


def _frames(src: Path, start: float, end: float, n: int = 3) -> list[str]:
    cap = cv2.VideoCapture(str(src))
    out = []
    for k in range(n):
        t = start + (end - start) * (k + 1) / (n + 1)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        frame = cv2.resize(frame, (768, int(h * 768 / w)))
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            out.append(base64.b64encode(jpg.tobytes()).decode())
    cap.release()
    return out


def shows_game(src: Path, start: float, end: float, game: str, cfg: dict) -> tuple[bool, str]:
    """(True/False, short description). Errors count as True so a hiccup never
    silently throws away clips."""
    frames = _frames(src, start, end)
    if not frames:
        return True, "no frames to check"
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": f}}
               for f in frames]
    content.append({"type": "text", "text": (
        f"These are 3 frames from one short clip of a livestream. Is the streamer playing "
        f"{game} in this clip, i.e. is {game} gameplay (or its in-game menus/map/cutscenes) "
        f"on screen in most of the frames? A small webcam of the streamer on top of the game "
        f"is normal. Answer false for IRL footage, just chatting, a desktop/browser, or a "
        f"different game.")})
    try:
        r = anthropic.Anthropic().messages.create(
            model=cfg["model"], max_tokens=2000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}])
        if r.stop_reason == "refusal":
            return True, "check declined"
        data = json.loads(next(b.text for b in r.content if b.type == "text"))
        return bool(data["shows_game"]), data["what_is_on_screen"][:80]
    except Exception as e:
        print(f"[gamecheck] skipped: {e}")
        return True, "check failed"
