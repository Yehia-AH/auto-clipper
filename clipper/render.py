"""Cut a clip, reframe it to 9:16 (face tracking or blurred background) and burn in captions."""
import json
import re
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
    m = max(14, gray.shape[1] // 80)  # small enough for tiny corner webcams
    return _CASCADE.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(m, m))


def track_speaker(path: Path, start: float, end: float, w: int, step: float = 0.5,
                  min_hits: float = 0.4):
    """Sample frames and return [(t_rel, (cx, cy, fw) | None)] or None if faces are rare."""
    cap = cv2.VideoCapture(str(path))
    scale = 1280 / w if w > 1280 else 1.0
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
    if not samples or hits / len(samples) < min_hits:
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


def split_graph_fixed(cam, w: int, h: int) -> str:
    """Webcam at a known spot (fractions x, y, w, h of the frame) on top, gameplay
    filling the rest underneath, with the webcam area kept out of it."""
    fx, fy, fw, fh = cam
    cx, cy = int(fx * w) // 2 * 2, int(fy * h) // 2 * 2
    cw, ch = max(2, int(fw * w) // 2 * 2), max(2, int(fh * h) // 2 * 2)
    top_h = min(900, max(400, int(OUT_W * ch / cw))) // 2 * 2
    bot_h = OUT_H - top_h
    game_w = min(w, int(h * OUT_W / bot_h)) // 2 * 2
    cam_l, cam_r = cx, cx + cw
    candidates = [(w - game_w) / 2, cam_r, cam_l - game_w]
    def overlap(x):
        return max(0.0, min(x + game_w, cam_r) - max(x, cam_l)) if cy < h * 0.5 else 0.0
    valid = [x for x in candidates if 0 <= x <= w - game_w] or [(w - game_w) / 2]
    game_x = int(min(valid, key=lambda x: (overlap(x), abs(x - (w - game_w) / 2)))) // 2 * 2
    return (f"[0:v]split[a][b];"
            f"[a]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{top_h},setsar=1[top];"
            f"[b]crop={game_w}:{h}:{game_x}:0,scale={OUT_W}:{bot_h},setsar=1[bot];"
            f"[top][bot]vstack[base]")


def split_graph(box, w: int, h: int) -> str:
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
            f"[b]crop={game_w}:{h}:{game_x}:0,scale=1080:1280,setsar=1[bot];"
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


_SWEARS = re.compile(r"\b(f)u(ck\w*)|\b(s)h(it\w*)|\b(b)i(tch\w*)|\b(c)u(nt\w*)"
                     r"|\b(p)u(ss(?:y|ies)\b)|\b(a)s(sholes?\b)|\b(n)i(gg\w*)",
                     re.IGNORECASE)


def censor(word: str) -> str:
    """Mask swear words in burned-in captions (F*CK): platforms can limit the reach
    of videos with visible profanity. The audio is untouched."""
    def mask(m):
        g = [x for x in m.groups() if x is not None]
        return g[0] + "*" + g[1]
    return _SWEARS.sub(mask, word)


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
        # the font has no emoji: drop them instead of drawing empty boxes
        safe = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", safe).strip()
        safe = censor(safe)
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
        if c.get("censor", True):
            word = censor(word)
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


# ---------------------------------------------------------------- unique edits
# Many clippers post the same streamer moments, and Instagram flags footage that
# matches other uploads as "not original". These edits make every clip visibly our
# own: zoom punch-ins on the loudest moments, a per-clip framing and colour grade,
# and a progress bar.

def loud_peaks(src: Path, start: float, dur: float, n: int = 3, gap: float = 6.0) -> list[float]:
    """Seconds (from clip start) of the n loudest moments, at least `gap` s apart."""
    try:
        raw = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(src),
             "-t", f"{dur:.2f}", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            check=True, capture_output=True, timeout=120).stdout
    except Exception:
        return []
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    win = 2000  # 0.25 s
    k = len(a) // win
    if k < 8:
        return []
    rms = np.sqrt(np.mean(a[:k * win].reshape(k, win) ** 2, axis=1) + 1e-10)
    loud = np.percentile(rms, 90)
    peaks: list[float] = []
    for i in np.argsort(-rms):
        t = i * 0.25
        if rms[i] < loud or t < 1.0 or t > dur - 1.5:
            continue
        if all(abs(t - p) >= gap for p in peaks):
            peaks.append(t)
        if len(peaks) >= n:
            break
    return sorted(peaks)


def unique_filter(clip: dict, peaks: list[float], fps: int = 30) -> str:
    """[base] -> [styled]: per-clip zoom + colour grade, with punch-ins at `peaks`."""
    import hashlib
    seed = int(hashlib.md5(f"{clip.get('title')}{clip['start']}".encode()).hexdigest()[:8], 16)
    rnd = lambda lo, hi, k: lo + (hi - lo) * ((seed >> (k * 4)) % 1000) / 999
    z0 = rnd(1.02, 1.06, 0)
    punch = "+".join(f"0.09*min(1,max(0,(it-{p - 0.1:.2f})/0.12))*min(1,max(0,({p + 1.1:.2f}-it)/0.2))"
                     for p in peaks) or "0"
    eq = (f"eq=contrast={rnd(1.02, 1.07, 1):.3f}:saturation={rnd(1.05, 1.18, 2):.3f}"
          f":brightness={rnd(-0.015, 0.02, 3):.3f}")
    # fps first: zoompan emits one frame per input frame, so a 60 fps stream fed
    # straight in plays at half speed (slow motion, out of sync with the audio)
    return (f"[base]fps={fps},zoompan=z='{z0:.3f}+{punch}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={OUT_W}x{OUT_H}:fps={fps},{eq},hue=h={rnd(-4, 4, 4):.1f},setsar=1[styled]")


def progress_bar(dur: float, color: str = "00E5FF") -> str:
    """[v0] -> [v]: a thin bar along the bottom that fills up as the clip plays."""
    return (f"color=c=0x{color}:s={OUT_W}x10:r=30[bar];"
            f"[v0][bar]overlay=x='-W+W*t/{dur:.2f}':y=H-10:shortest=1[v]")


# ---------------------------------------------------------------- render

def render_clip(src: Path, clip: dict, out: Path, cfg: dict, overlay: str | None = None,
                webcam: list | None = None, gameplay_only: bool = False) -> str:
    """Render one vertical clip. Returns the layout used."""
    w, h = probe(src)
    start, end = clip["start"], clip["end"]
    dur = end - start
    cw = int(h * 9 / 16) // 2 * 2

    layout = cfg["layout"]
    plan = box = None
    if webcam and layout in ("auto", "split") and cw < w and cfg.get("webcam_check", True):
        # the known webcam spot can be empty (streaming without a camera, or the
        # camera moved): never show a random corner of the game as "the webcam"
        from .gamecheck import has_webcam
        if not has_webcam(src, start, end, webcam, cfg):
            print("[render] no webcam in its usual spot for this clip")
            webcam = None
            if gameplay_only:
                layout = "zoom"  # gameplay fills the screen instead
    if cw >= w:  # source already vertical-ish
        layout = "blur"
    elif webcam and layout in ("auto", "split") and gameplay_only:
        # gameplay-only campaign with a known webcam spot: IRL clips are already
        # dropped, so always stack (a cutscene close-up must not look like IRL)
        layout = "fixedsplit"
    elif webcam and layout in ("auto", "split"):
        # the streamer's webcam spot is known: only check for IRL footage, where
        # a big face fills the camera and there is no webcam overlay
        samples = track_speaker(src, start, end, w, min_hits=0.3)
        big = samples and float(np.median([b[2] for _, b in samples if b])) >= 0.10 * w
        if big:
            plan = crop_plan(samples, w, cw)
            layout = "crop"
        else:
            layout = "fixedsplit"
    elif layout in ("auto", "split"):
        # a forced split only needs to find the (static) webcam a few times
        samples = track_speaker(src, start, end, w, min_hits=0.15 if layout == "split" else 0.4)
        if not samples:
            layout = "zoom"  # no webcam: fill the screen with gameplay instead
        elif layout == "split":
            boxes = [b for _, b in samples if b]
            box = tuple(float(np.median([b[i] for b in boxes])) for i in range(3))
            if box[2] >= 0.10 * w:
                # a big face means the camera IS the picture (IRL / just chatting),
                # not a webcam over gameplay: stacking would show the scene twice
                box = None
                plan = crop_plan(samples, w, cw)
                layout = "crop"
        elif (box := webcam_box(samples, w, h)):
            layout = "split"
        else:
            plan = crop_plan(samples, w, cw)
            layout = "crop"
    elif layout == "crop":
        plan = [(0.0, (w - cw) // 2 // 2 * 2)]

    if layout == "fixedsplit":
        graph = split_graph_fixed(webcam, w, h)
        layout = "split"
    elif layout == "split":
        graph = split_graph(box, w, h)
    elif layout == "crop":
        x = _crop_x_expr(plan)
        graph = f"[0:v]crop={cw}:{h}:{x}:0,scale={OUT_W}:{OUT_H},setsar=1[base]"
    elif layout == "zoom":
        # gameplay zoomed to a big 4:5 panel (1080x1350) on a blurred backdrop
        zw = min(w, int(h * 4 / 5)) // 2 * 2
        graph = (f"[0:v]split[a][b];"
                 f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                 f"crop={OUT_W}:{OUT_H},boxblur=25:4,eq=brightness=-0.08[bg];"
                 f"[b]crop={zw}:{h}:{(w - zw) // 2 // 2 * 2}:0,scale={OUT_W}:1350,setsar=1[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")
    else:
        graph = (f"[0:v]split[a][b];"
                 f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                 f"crop={OUT_W}:{OUT_H},boxblur=25:4,eq=brightness=-0.08[bg];"
                 f"[b]scale={OUT_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")

    cap = cfg["captions"]
    workdir = out.parent
    if cap["enabled"]:
        ass_name = out.stem + ".ass"
        (workdir / ass_name).write_text(build_ass(
            clip["words"], start, end, clip.get("title") if cap.get("show_title", True) else None, cap,
            title_y=610 if layout == "split" else 230, overlay=overlay))
    if cfg.get("unique_edits", True):
        peaks = loud_peaks(src.resolve(), start, dur)
        graph += ";" + unique_filter(clip, peaks)
        base = "[styled]"
    else:
        base = "[base]"
    if cap["enabled"]:
        graph += f";{base}ass={ass_name}[v0]"
    else:
        graph += f";{base}null[v0]"
    graph += ";" + (progress_bar(dur, cap.get("highlight_color", "00E5FF"))
                    if cfg.get("unique_edits", True) else "[v0]null[v]")

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(src.resolve()),
           "-t", f"{dur:.2f}", "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
           "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "6M", "-bufsize", "12M",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
           out.name]
    subprocess.run(cmd, check=True, cwd=workdir)
    if cap["enabled"]:
        (workdir / ass_name).unlink(missing_ok=True)
    return layout
