# Auto Clipper ✂️

> 📒 **How we actually run it, costs, campaign rules and lessons learned: [PLAYBOOK.md](PLAYBOOK.md)**

## Use it yourself (free, MIT licensed)

1. **Fork** this repo (top right → Fork). Keep your fork **public** so GitHub Actions is free.
2. In your fork: **Settings → Secrets and variables → Actions**, add `ANTHROPIC_API_KEY`
   (+ `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to get clips on your phone). See setup below.
3. **Actions** tab → enable workflows.
4. Edit `config.yaml`: set **`paused: false`**, and replace the `sources:` with the
   streamer(s) you clip (Twitch: `live: true` to record while live; `require_game`
   to keep only one game; `hashtags`, `notes` and `reminder` for the campaign rules).
5. Optional: empty `state/processed.json` to `{}` so you start with a clean history.

That's it: a watcher checks every 5 minutes, records the stream while it's live and
sends ~4 clips per stream hour to Telegram. The only cost is Claude API usage while
clipping. Only clip creators who allow it (e.g. paid clipping campaigns).

Turns long videos (podcasts, streams, interviews) into ready-to-post vertical
clips, automatically, every hour. You only do the posting.

```
new upload on a watched channel
  → download (yt-dlp)
  → transcribe with word timings (Whisper)
  → Claude picks the best 30–60s moments + writes title, caption, hashtags
  → cut to 9:16, camera follows the speaker's face (or blurred-background layout)
  → burn in word-by-word highlighted captions + hook title
  → sends each clip + caption to your phone on Telegram, and saves them as a GitHub release
```

## One-time setup (≈10 minutes)

### 1. Add secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required | What it is |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | From console.anthropic.com → API Keys. Picks the moments (a few cents per video). |
| `TELEGRAM_BOT_TOKEN` | recommended | Clips land on your phone. Message **@BotFather** on Telegram → `/newbot` → copy the token. |
| `TELEGRAM_CHAT_ID` | recommended | Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`. |
| `YTDLP_COOKIES` | if downloads fail | YouTube often blocks GitHub's servers ("Sign in to confirm you're not a bot"). Export your YouTube cookies with the "Get cookies.txt LOCALLY" browser extension and paste the whole file in here. Use a spare Google account. |

### 2. Pick what to clip
Edit `config.yaml` and add channels or playlists under `sources:`. Also set
`niche_notes` to describe your audience. That's what steers which moments get picked.

> Only clip content you have the rights to: your own, or creators running a
> clipping campaign (Whop Content Rewards, Vyro, etc.) that pays you for clips.

### 3. Run it
**Actions → Auto Clip → Run workflow.** Paste a video URL to test one right away,
or leave it empty to check your sources. After that it runs every hour on its own.

## Live streams
Add a channel and it clips both uploads and past live streams:
- `https://www.youtube.com/@Creator`: uploads + the /streams tab
- `https://www.twitch.tv/creator`: past broadcasts (VODs)

Streams are clipped after they end, once the VOD is up (it checks every hour).
Long streams are handled differently: downloaded at 720p, transcribed with a
faster model, and scanned one hour at a time so moments late in the stream get
found too (`stream_clips_per_hour`, default 3). Streams longer than
`max_stream_hours` (8) are clipped in 8-hour parts, one part per run (GitHub stops a job after 6 hours).

For gaming / reaction streams, `layout: auto` spots a small webcam in a corner and
switches to a split layout: webcam on top, gameplay underneath.

**Clipping while live (Twitch):** set `live: true` on a source. The Live Recorder
workflow watches every 5 minutes, records the broadcast itself (no gaps, handing
over between runs on the hour), reads live chat, skips breaks and hours spent on
another game, and clips each finished hour about 15 minutes after it ends.

## Posting
Each clip arrives in Telegram with the caption + hashtags already written. Save
the video, open TikTok / Shorts / Reels, paste the caption, post. Everything is
also under **Releases** in this repo.

Tips: post 2–4 clips a day per account, change the first second of the hook
if a clip underperforms, and avoid posting the exact same file to many accounts.

## Settings worth knowing (`config.yaml`)
- `clips_per_video`, `min_clip_seconds`, `max_clip_seconds`
- `layout`: `auto` (face tracking + webcam detection), `split` (webcam on top, game below), `crop`, or `blur` (screen recordings)
- `captions`: font, size, colors, words per line, uppercase, hook title on/off
- `whisper_model`: `small` is a good balance; `medium` is more accurate but slower
- `max_videos_per_run`: keeps each run inside GitHub's 6-hour limit

## Run on your own computer
Needs Python 3.10+ and ffmpeg.
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python -m clipper url "https://www.youtube.com/watch?v=..."
python -m clipper file my_podcast.mp4
python -m clipper run          # check all sources in config.yaml
```
Clips are written to `output/`.

## Costs
GitHub Actions is free for public repos and has 2,000 free minutes/month for
private repos (a 1-hour video takes roughly 20–40 min). Claude costs a few
cents per video.
