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
        f"These are 3 frames from one short clip of a livestream. Is a video game being played "
        f"in this clip: gameplay (or in-game menus, map or cutscenes) on screen in most of the "
        f"frames? The game is most likely {game}, a brand-new game you may not recognise, so "
        f"do NOT try to identify the game: any video game gameplay counts as true. A small "
        f"webcam of the streamer over the game is normal. Answer false only for IRL camera "
        f"footage, just chatting with no game on screen, or a desktop/browser.")})
    try:
        r = anthropic.Anthropic().messages.create(
            model=cfg.get("check_model") or cfg["model"], max_tokens=2000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}])
        if r.stop_reason == "refusal":
            return True, "check declined"
        data = json.loads(next(b.text for b in r.content if b.type == "text"))
        return bool(data["shows_game"]), data["what_is_on_screen"][:80]
    except Exception as e:
        print(f"[gamecheck] skipped: {e}")
        return True, "check failed"


CAM_SCHEMA = {
    "type": "object",
    "properties": {"webcam_frames": {"type": "integer", "description": "How many of the images show a real webcam person"}},
    "required": ["webcam_frames"],
    "additionalProperties": False,
}


def has_webcam(src: Path, start: float, end: float, box: list, cfg: dict) -> bool:
    """Is the streamer's webcam really in `box` ([x, y, w, h] fractions) during this
    clip? Streamers sometimes stream without their camera or move it, and the clip
    must not show a random corner of the game as "the webcam". Errors count as True."""
    cap = cv2.VideoCapture(str(src))
    crops = []
    for k in range(3):
        t = start + (end - start) * (k + 1) / 4
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        x0, y0 = int(box[0] * w), int(box[1] * h)
        crop = frame[y0:y0 + max(int(box[3] * h), 2), x0:x0 + max(int(box[2] * w), 2)]
        crop = cv2.resize(crop, (480, int(crop.shape[0] * 480 / max(crop.shape[1], 1))))
        ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            crops.append(base64.b64encode(jpg.tobytes()).decode())
    cap.release()
    if not crops:
        return True
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": c}}
               for c in crops]
    content.append({"type": "text", "text": (
        f"These {len(crops)} images are the same corner of a gaming livestream, where the "
        "streamer's webcam usually sits. Count how many images show a REAL-LIFE webcam "
        "feed of a person (a real human on camera, e.g. in their room with headphones). "
        "Video game graphics, game characters, menus, maps or cutscenes do NOT count, "
        "even if they show a person.")})
    try:
        r = anthropic.Anthropic().messages.create(
            model=cfg.get("check_model") or cfg["model"], max_tokens=1000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": CAM_SCHEMA}},
            messages=[{"role": "user", "content": content}])
        if r.stop_reason == "refusal":
            return True
        n = int(json.loads(next(b.text for b in r.content if b.type == "text"))["webcam_frames"])
        return n * 2 >= len(crops)  # most of the clip
    except Exception as e:
        print(f"[webcam] check skipped: {e}")
        return True
