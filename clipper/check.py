"""Setup check: verifies each key works, without clipping anything.

  python -m clipper.check [optional video URL to test downloading]
"""
import os
import sys

from .config import load_config

OK, BAD, SKIP = "✅", "❌", "⚪"


def check_claude(cfg) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return f"{BAD} Claude: ANTHROPIC_API_KEY secret is missing"
    import anthropic
    try:
        r = anthropic.Anthropic().messages.create(
            model=cfg["model"], max_tokens=200, output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with just: ready"}])
        return f"{OK} Claude: key works ({r.model})"
    except anthropic.AuthenticationError:
        return f"{BAD} Claude: key was rejected. Re-copy it into ANTHROPIC_API_KEY"
    except anthropic.PermissionDeniedError as e:
        return f"{BAD} Claude: no permission ({e.message[:120]})"
    except anthropic.BadRequestError as e:
        msg = e.message.lower()
        if "credit" in msg or "billing" in msg:
            return f"{BAD} Claude: no credit on the account. Add some under Billing"
        return f"{BAD} Claude: {e.message[:150]}"
    except anthropic.APIError as e:
        return f"{BAD} Claude: {str(e)[:150]}"


def check_telegram() -> str:
    import requests
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token and not chat:
        return f"{SKIP} Telegram: not set up (clips will only go to GitHub Releases)"
    if not token or not chat:
        missing = "TELEGRAM_BOT_TOKEN" if not token else "TELEGRAM_CHAT_ID"
        return f"{BAD} Telegram: {missing} secret is missing"
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                      data={"chat_id": chat, "text": "✅ Auto Clipper is connected. Clips will arrive here."})
    if r.ok:
        return f"{OK} Telegram: test message sent, check your phone"
    desc = r.json().get("description", r.text)[:150] if r.headers.get("content-type", "").startswith("application/json") else r.text[:150]
    if r.status_code in (401, 404):
        return (f"{BAD} Telegram: bot token is wrong ({desc}). Copy it again from @BotFather: "
                "it looks like 123456789:AAH..., with no spaces, quotes or the word 'bot' in front")
    if "chat not found" in desc.lower():
        return f"{BAD} Telegram: chat not found. Press Start in your bot, and check TELEGRAM_CHAT_ID ({desc})"
    return f"{BAD} Telegram: {desc}"


def check_download(url: str) -> str:
    from . import fetch
    try:
        info = fetch.probe_url(url)
        mins = (info.get("duration") or 0) / 60
        return f"{OK} Video access: can read \"{info.get('title', '?')[:60]}\" ({mins:.0f} min)"
    except Exception as e:
        hint = (" YouTube is blocking GitHub's servers: add your cookies as the YTDLP_COOKIES secret (see README)."
                if "bot" in str(e).lower() or "sign in" in str(e).lower() else "")
        return f"{BAD} Video access: {str(e)[:150]}{hint}"


def main() -> None:
    cfg = load_config()
    results = [check_claude(cfg), check_telegram()]
    url = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    if url:
        results.append(check_download(url))
    srcs = cfg["sources"]
    results.append(f"{OK} Sources: {len(srcs)} in config.yaml" if srcs
                   else f"{SKIP} Sources: none yet in config.yaml")
    print("\n".join(results))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("## Setup check\n\n" + "\n".join(f"- {r}" for r in results) + "\n")
    if any(r.startswith(BAD) for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
