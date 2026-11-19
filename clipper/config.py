from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "sources": [],
    "lookback_videos": 3,
    "max_videos_per_run": 2,
    "min_source_minutes": 5,
    "clips_per_video": 5,
    "min_clip_seconds": 20,
    "max_clip_seconds": 60,
    "niche_notes": "",
    "model": "claude-opus-5-5",
    "effort": "medium",
    "whisper_model": "small",
    "long_video_minutes": 90,
    "stream_whisper_model": "base",
    "stream_clips_per_hour": 3,
    "max_clips_per_video": 15,
    "min_score": 6,
    "digest_hour": 12,
    "digest_count": 6,
    "utc_offset_hours": 3,
    "max_stream_hours": 8,
    "stream_part_hours": 4,
    "processing_ratio": 0.5,
    "language": None,
    "layout": "auto",
    "captions": {
        "enabled": True,
        "font": "DejaVu Sans",
        "font_size": 78,
        "words_per_line": 3,
        "uppercase": True,
        "show_title": True,
        "color": "FFFFFF",
        "highlight_color": "00E5FF",
        "outline": 5,
        "position_from_bottom": 520,
    },
    "output_dir": "output",
}


def load_config(path: str | Path = ROOT / "config.yaml") -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        user = yaml.safe_load(p.read_text()) or {}
        captions = {**DEFAULTS["captions"], **(user.pop("captions", None) or {})}
        cfg.update({k: v for k, v in user.items() if v is not None or k == "language"})
        cfg["captions"] = captions
    # older configs used max_stream_hours for the part length
    if "stream_part_hours" not in user_keys(path) and "max_stream_hours" in user_keys(path):
        cfg["stream_part_hours"] = cfg["max_stream_hours"]
    cfg["sources"] = [normalize_source(s) for s in (cfg.get("sources") or [])]
    return cfg


def user_keys(path) -> set:
    p = Path(path)
    return set((yaml.safe_load(p.read_text()) or {}).keys()) if p.exists() else set()


def normalize_source(s) -> dict:
    """A source is either a plain URL or a dict with campaign rules:
    {url, name, hashtags, notes, overlay, reminder}."""
    if isinstance(s, str):
        s = {"url": s}
    s = dict(s)
    s["url"] = str(s["url"]).strip()
    s["hashtags"] = ["#" + str(h).lstrip("#").replace(" ", "") for h in (s.get("hashtags") or [])]
    for k in ("name", "notes", "overlay", "reminder", "since", "layout", "require_game"):
        s[k] = str(s.get(k) or "").strip()
    s.setdefault("auto", True)  # False = only clip when a URL is run by hand
    s["single_stream"] = bool(s.get("single_stream", False))  # stop after one long stream
    cam = s.get("webcam")  # [x, y, w, h] as fractions of the frame, if known
    s["webcam"] = [float(v) for v in cam] if cam and len(cam) == 4 else None
    return s
