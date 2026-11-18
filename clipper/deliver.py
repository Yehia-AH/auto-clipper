"""Send finished clips to your phone via a Telegram bot (optional)."""
import os
from pathlib import Path

import requests


def telegram_enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.environ["TELEGRAM_BOT_TOKEN"].strip()}/{method}"


def send_message(text: str) -> None:
    requests.post(_api("sendMessage"), timeout=60, data={
        "chat_id": os.environ["TELEGRAM_CHAT_ID"].strip(), "text": text[:4000],
        "disable_web_page_preview": True})


def send_clip(video: Path, post_text: str) -> None:
    """Upload a clip with its ready-to-paste caption. Bots can send files up to 50 MB."""
    if video.stat().st_size > 49 * 1024 * 1024:
        send_message(f"{video.name} is over 50 MB, grab it from the GitHub release.\n\n{post_text}")
        return
    with video.open("rb") as f:
        r = requests.post(_api("sendVideo"), timeout=600, data={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"].strip(),
            "caption": post_text[:1024],
            "supports_streaming": True,
        }, files={"video": (video.name, f, "video/mp4")})
    if not r.ok:
        print(f"[telegram] failed to send {video.name}: {r.status_code} {r.text[:200]}")
