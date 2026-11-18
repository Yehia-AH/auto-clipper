"""Find nudity in a clip (e.g. GTA strip club / shower scenes) so it can be blurred
or the clip dropped. Uses NudeNet (open-source detector, runs offline on CPU)."""
from pathlib import Path

import cv2

# Only exposed parts count; covered / face / feet labels are fine for socials.
EXPOSED = {
    "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED",
    "BUTTOCKS_EXPOSED", "ANUS_EXPOSED",
}

_DETECTOR = None


def _detector():
    global _DETECTOR
    if _DETECTOR is None:
        from nudenet import NudeDetector
        _DETECTOR = NudeDetector()
    return _DETECTOR


def nsfw_intervals(src: Path, start: float, end: float, min_score: float = 0.45,
                   step: float = 0.5, pad: float = 0.75) -> tuple[list[tuple[float, float]], float]:
    """Return ([(a, b), ...] seconds relative to the clip start that need blurring,
    fraction of the clip that is flagged)."""
    cap = cv2.VideoCapture(str(src))
    hits = []
    t = start
    total = 0
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        total += 1
        h, w = frame.shape[:2]
        if w > 960:
            frame = cv2.resize(frame, (960, int(h * 960 / w)))
        found = [d for d in _detector().detect(frame)
                 if d["class"] in EXPOSED and d["score"] >= min_score]
        if found:
            hits.append(t - start)
        t += step
    cap.release()
    if not hits:
        return [], 0.0
    # merge nearby hits into padded intervals
    intervals = []
    for h in hits:
        a, b = max(0.0, h - pad), h + step + pad
        if intervals and a <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], b)
        else:
            intervals.append((a, b))
    return intervals, len(hits) / max(total, 1)


def enable_expr(intervals: list[tuple[float, float]]) -> str:
    """ffmpeg 'enable' expression (commas escaped for a filtergraph)."""
    return "+".join(f"between(t\\,{a:.2f}\\,{b:.2f})" for a, b in intervals)
