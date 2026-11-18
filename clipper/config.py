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
    cfg["sources"] = cfg.get("sources") or []
    return cfg
