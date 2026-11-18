"""Send finished clips to your phone via a Telegram bot (optional).

Delivery never raises: a Telegram hiccup must not lose a run's clips or progress
(they're also published as a GitHub release)."""
import os
import time
from pathlib import Path

import requests


def telegram_enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN'].strip()}/{method}"


def _post(method: str, data: dict, video: Path | None = None, tries: int = 4) -> bool:
    for attempt in range(1, tries + 1):
        try:
            if video:
                with video.open("rb") as f:
                    r = requests.post(_api(method), timeout=600, data=data,
                                      files={"video": (video.name, f, "video/mp4")})
            else:
                r = requests.post(_api(method), timeout=60, data=data)
            if r.ok:
                return True
            if r.status_code == 429:  # rate limited: Telegram says how long to wait
                wait = r.json().get("parameters", {}).get("retry_after", 5)
            elif r.status_code >= 500:
                wait = 5 * attempt
            else:
                print(f"[telegram] {method} failed: {r.status_code} {r.text[:200]}")
                return False
        except requests.RequestException as e:
            print(f"[telegram] {method} attempt {attempt}/{tries}: {e}")
            wait = 5 * attempt
        time.sleep(wait)
    print(f"[telegram] {method} gave up after {tries} tries")
    return False


def send_message(text: str) -> bool:
    return _post("sendMessage", {"chat_id": os.environ["TELEGRAM_CHAT_ID"].strip(),
                                 "text": text[:4000], "disable_web_page_preview": True})


def send_clip(video: Path, post_text: str) -> bool:
    """Upload a clip with its ready-to-paste caption. Bots can send files up to 50 MB."""
    if video.stat().st_size > 49 * 1024 * 1024:
        return send_message(f"{video.name} is over 50 MB, grab it from the GitHub release.\n\n{post_text}")
    ok = _post("sendVideo", {"chat_id": os.environ["TELEGRAM_CHAT_ID"].strip(),
                             "caption": post_text[:1024], "supports_streaming": True}, video)
    time.sleep(1)  # stay well under Telegram's rate limits
    return ok
