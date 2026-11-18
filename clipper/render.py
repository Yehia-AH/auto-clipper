"""Cut a clip, reframe it to 9:16 (face tracking or blurred background) and burn in captions."""
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

OUT_W, OUT_H = 1080, 1920


def probe(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:stream_side_data=rotation", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    w, h = s["width"], s["height"]
    rot = next((abs(int(d.get("rotation", 0))) for d in s.get("side_data_list", [])), 0)
    return (h, w) if rot in (90, 270) else (w, h)


# ---------------------------------------------------------------- face tracking

_CASCADE = None


def _faces(frame) -> list:
    global _CASCADE
    if _CASCADE is None:
        _CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    m = gray.shape[1] // 40
    return _CASCADE.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(m, m))


def track_speaker(path: Path, start: float, end: float, w: int, step: float = 0.5):
    """Sample frames and return [(t_rel, (cx, cy, fw) | None)] or None if faces are rare."""
    cap = cv2.VideoCapture(str(path))
    scale = 960 / w if w > 960 else 1.0
    samples = []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        if scale != 1.0:
            frame = cv2.resize(frame, None, fx=scale, fy=scale)
        faces = _faces(frame)
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])  # biggest face
            samples.append((t - start, ((x + fw / 2) / scale, (y + fh / 2) / scale, fw / scale)))
        else:
            samples.append((t - start, None))
        t += step
    cap.release()
    hits = sum(1 for _, x in samples if x is not None)
    if not samples or hits / len(samples) < 0.4:
        return None
    return samples


def crop_plan(samples, w: int, cw: int, step: float = 0.5) -> list[tuple[float, int]]:
    """Turn noisy face positions into a few stable 'camera positions' [(t, x)]."""
    xs = [b[0] if b else None for _, b in samples]
    # fill gaps with nearest known value
    last = next(x for x in xs if x is not None)
    for i, x in enumerate(xs):
        xs[i] = last = x if x is not None else last
    xs = np.array(xs, dtype=float)
    k = 5  # median smoothing (~2.5s)
    pad = np.pad(xs, (k // 2, k // 2), mode="edge")
    smooth = np.array([np.median(pad[i:i + k]) for i in range(len(xs))])

    def clamp(cx):
        return int(min(max(cx - cw / 2, 0), w - cw)) // 2 * 2

    plan = [(0.0, clamp(smooth[0]))]
    current = smooth[0]
    i = 0
    while i < len(smooth):
        # move the "camera" only when the speaker stays away for >= 1s
        if abs(smooth[i] - current) > 0.10 * w and i + 1 < len(smooth) and \
                abs(smooth[i + 1] - current) > 0.10 * w:
            current = smooth[i]
            plan.append((round(samples[i][0], 2), clamp(current)))
            i += 2
            continue
        i += 1
    return plan[:40]


def webcam_box(samples, w: int, h: int):
    """If the face is a small webcam overlay near a corner (typical gaming / reaction
    stream), return its median (cx, cy, fw). Otherwise None."""
    boxes = [b for _, b in samples if b]
    cx, cy, fw = (float(np.median([b[i] for b in boxes])) for i in range(3))
    # A face this small is almost always a webcam overlay on top of gameplay,
    # wherever the streamer put it. (Podcast / IRL faces are much bigger.)
    small = fw < 0.07 * w
    return (cx, cy, fw) if small else None


def split_graph(box, w: int, h: int, blur: str = "") -> str:
    """Webcam on top (1080x640), gameplay underneath (1080x1280)."""
    cx, cy, fw = box
    cam_w = min(w, int(fw * 5))
    cam_h = int(cam_w * 640 / 1080)
    if cam_h > h:
        cam_h, cam_w = h, int(h * 1080 / 640)
    cam_w, cam_h = cam_w // 2 * 2, cam_h // 2 * 2
    cam_x = int(min(max(cx - cam_w / 2, 0), w - cam_w)) // 2 * 2
    cam_y = int(min(max(cy - cam_h * 0.45, 0), h - cam_h)) // 2 * 2
    game_w = min(w, int(h * 1080 / 1280)) // 2 * 2
    # keep the webcam out of the gameplay panel when there's room to
    cam_l, cam_r = cx - fw * 3.2, cx + fw * 3.2
    candidates = [(w - game_w) / 2, cam_r, cam_l - game_w]
    def overlap(x):
        return max(0.0, min(x + game_w, cam_r) - max(x, cam_l))
    valid = [x for x in candidates if 0 <= x <= w - game_w] or [(w - game_w) / 2]
    best = min(valid, key=lambda x: (overlap(x), abs(x - (w - game_w) / 2)))
    game_x = int(best) // 2 * 2
    return (f"[0:v]split[a][b];"
            f"[a]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},scale=1080:640,setsar=1[top];"
            f"[b]crop={game_w}:{h}:{game_x}:0,scale=1080:1280,setsar=1{blur}[bot];"
            f"[top][bot]vstack[base]")


def _crop_x_expr(plan) -> str:
    expr = str(plan[-1][1])
    for (t_next, _), (_, x) in reversed(list(zip(plan[1:], plan[:-1]))):
        expr = f"if(lt(t\\,{t_next})\\,{x}\\,{expr})"
    return expr


# ---------------------------------------------------------------- captions

def _ass_color(rrggbb: str) -> str:
    r, g, b = rrggbb[0:2], rrggbb[2:4], rrggbb[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(words: list[dict], clip_start: float, clip_end: float, title: str | None,
              cfg: dict, title_y: int = 230, overlay: str | None = None) -> str:
    c = cfg
    font, size = c["font"], c["font_size"]
    col, hi = _ass_color(c["color"]), _ass_color(c["highlight_color"])
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {OUT_W}", f"PlayResY: {OUT_H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{col},{col},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{c['outline']},2,2,70,70,{c['position_from_bottom']},1",
        f"Style: Title,{font},{int(size * 0.72)},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,"
        f"-1,0,0,0,100,100,0,0,3,18,0,8,90,90,{title_y},1",
        f"Style: Tag,{font},{int(size * 0.55)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,60,60,150,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    dur = clip_end - clip_start
    if title:
        safe = title.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(dur)},Title,,0,0,0,,{safe}")
    if overlay:  # e.g. the streamer's handle, when a campaign requires it on screen
        safe = overlay.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(dur)},Tag,,0,0,0,,{safe}")

    # group words into short chunks; break on pauses
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= c["words_per_line"] or w["start"] - cur[-1]["end"] > 0.6):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    def fmt(word):
        word = word.replace("{", "(").replace("}", ")")
        return word.upper() if c["uppercase"] else word

    for ci, chunk in enumerate(chunks):
        next_start = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else clip_end
        for wi, w in enumerate(chunk):
            s = w["start"]
            e = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else min(w["end"] + 0.4, next_start)
            parts = []
            for j, other in enumerate(chunk):
                if j == wi:
                    parts.append(f"{{\\c{hi}&\\fscx108\\fscy108}}{fmt(other['word'])}{{\\c{col}&\\fscx100\\fscy100}}")
                else:
                    parts.append(fmt(other["word"]))
            lines.append(f"Dialogue: 0,{_ts(s - clip_start)},{_ts(e - clip_start)},Cap,,0,0,0,,"
                         + " ".join(parts))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- render

class UnsafeClip(Exception):
    """The clip is mostly nudity; don't post it."""


def render_clip(src: Path, clip: dict, out: Path, cfg: dict, overlay: str | None = None) -> str:
    """Render one vertical clip. Returns the layout used."""
    w, h = probe(src)
    start, end = clip["start"], clip["end"]
    dur = end - start
    cw = int(h * 9 / 16) // 2 * 2

    layout = cfg["layout"]
    plan = box = None
    if cw >= w:  # source already vertical-ish
        layout = "blur"
    elif layout in ("auto", "split"):
        samples = track_speaker(src, start, end, w)
        if not samples:
            layout = "blur"
        elif layout == "split":
            boxes = [b for _, b in samples if b]
            box = tuple(float(np.median([b[i] for b in boxes])) for i in range(3))
        elif (box := webcam_box(samples, w, h)):
            layout = "split"
        else:
            plan = crop_plan(samples, w, cw)
            layout = "crop"
    elif layout == "crop":
        plan = [(0.0, (w - cw) // 2 // 2 * 2)]

    # Nudity (GTA strip club / shower scenes): blur the gameplay where it shows up,
    # or drop the clip when it's most of it.
    blur = ""
    if cfg.get("nsfw_filter", True):
        from .safety import enable_expr, nsfw_intervals
        intervals, frac = nsfw_intervals(src, start, end)
        if frac > cfg.get("nsfw_max_fraction", 0.4):
            raise UnsafeClip(f"nudity in {frac:.0%} of the clip")
        if intervals:
            blur = f",boxblur=luma_radius=60:luma_power=4:enable='{enable_expr(intervals)}'"
            clip["blurred"] = [[round(a, 1), round(b, 1)] for a, b in intervals]

    if layout == "split":
        graph = split_graph(box, w, h, blur)
    elif layout == "crop":
        x = _crop_x_expr(plan)
        graph = f"[0:v]crop={cw}:{h}:{x}:0,scale={OUT_W}:{OUT_H},setsar=1[base]"
    else:
        graph = (f"[0:v]split[a][b];"
                 f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                 f"crop={OUT_W}:{OUT_H},boxblur=25:4,eq=brightness=-0.08[bg];"
                 f"[b]scale={OUT_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")

    if blur and layout != "split":  # whole picture is gameplay
        graph = graph[: -len("[base]")] + f"[pre];[pre]null{blur}[base]"

    cap = cfg["captions"]
    workdir = out.parent
    if cap["enabled"]:
        ass_name = out.stem + ".ass"
        (workdir / ass_name).write_text(build_ass(
            clip["words"], start, end, clip.get("title") if cap.get("show_title", True) else None, cap,
            title_y=610 if layout == "split" else 230, overlay=overlay))
        graph += f";[base]ass={ass_name}[v]"
    else:
        graph += ";[base]null[v]"

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(src.resolve()),
           "-t", f"{dur:.2f}", "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
           "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           out.name]
    subprocess.run(cmd, check=True, cwd=workdir)
    if cap["enabled"]:
        (workdir / ass_name).unlink(missing_ok=True)
    return layout
