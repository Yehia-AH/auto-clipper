# Clip Farming Playbook

Everything we built and learned running this bot on real clipping campaigns
(Nov 2026), so nothing has to be figured out twice. The setup guide is in
`README.md`; this file is the "how we actually run it" part.

- **[docs/FULL_HISTORY.md](docs/FULL_HISTORY.md)**: every message of the whole project, in order
- **[docs/CODE_CHANGES.md](docs/CODE_CHANGES.md)**: every code change, with why

## Status right now

**Paused** (`paused: true` at the top of `config.yaml`). Nothing watches, records,
clips or calls Claude, so it costs $0. To restart: set `paused: false` and push
(or tell Claude "unpause").

## How it works

```
👀 Watcher (live.yml)  checks Twitch every 5 min whether a `live: true` streamer is live
   │ live!
🔴 Recorder (live.yml) records the stream itself, split at every full stream hour
   │                   reads Twitch chat (spikes, "clip it", mood) and the stream category
   │ each finished hour
⏭  Skip?               on a break (hardly talking) or not the campaign's game → skipped, no Claude
✂️ Clip                Whisper transcript + loudness + chat + game events
                       → Sonnet picks moments (strict rubric) → Haiku ranks them
                       → Haiku checks it's gameplay + the webcam is really there
                       → 1080x1920 render: webcam on top / gameplay below (or full
                         gameplay if no webcam), hook title, word captions (swears
                         masked), zoom punch-ins, per-clip colour, progress bar
📦 Deliver             Telegram (video + caption + 𝕏 caption) and a GitHub release
```

A GitHub job can run 6 h max, so the recorder hands over to a fresh run on the
hour boundary every ~3-4 h. When the stream ends it goes back to watching.

| Workflow | What it's for |
|---|---|
| **Live Recorder** (`live.yml`) | Watching + recording live streams (the main one) |
| **Auto Clip** (`clip.yml`) | Saved recordings (VODs), hand-picked links, re-making hours (`parts=3-3`) |
| **Re-edit clips** (`reedit.yml`) | Re-render existing clips with the current look: finds each clip's exact moment in the VOD by its audio |
| **Setup check** (`check.yml`) | Checks the secrets work |

Claude starts runs by committing `requests/run.txt`, `requests/live.txt` or
`requests/reedit.json` (it can't press "Run workflow").

## Key settings (`config.yaml`)

| Setting | Value | Meaning |
|---|---|---|
| `paused` | true | Master off switch |
| `model` | claude-sonnet-5-5 | Picks the moments (was Opus; Sonnet is half the price) |
| `check_model` | claude-haiku-5-5 | Ranking, gameplay check, webcam check |
| `stream_clips_per_hour` | 4 | Max clips per stream hour |
| `min_score` | 7 | Keep moments rated 7/10+ (strict rubric: 7 = strong) |
| `min_words_per_minute` | 20 | Below this an hour counts as a break and is skipped |
| Source `live: true` | | Record this streamer while live |
| Source `require_game` | GTA 6 | Only keep gameplay of this game; non-GTA hours skipped via the Twitch category |
| Source `webcam` | [0,0,0.248,0.247] | Where the webcam usually is (checked per clip) |

## Costs

**Paid:** only Anthropic API credits, and only while clipping (Sonnet picking +
a few tiny Haiku checks per stream hour). The Claude chat subscription does NOT
cover the bot (API and subscription are billed separately). Usage:
console.anthropic.com → Usage.

**Free:** GitHub Actions (because the repo is **public**; keep it public, a
private repo gets ~2,000 min/month), GitHub releases, Telegram, Twitch, yt-dlp,
ffmpeg, Whisper, the watcher, skipped hours.

First week (Opus + lots of testing): ~$15.

## New campaign checklist

1. Send Claude the **full rules page or paste the full rules text**, and save it
   word for word in this file (below) before starting.
2. List every number back: pool, split, **minimum views per video**, **minimum
   total views to get paid**, max payout, deadline after posting, platforms.
3. Add the streamer to `config.yaml` (name, hashtags, notes, reminder, `live`,
   `require_game`, webcam spot), set `paused: false`.
4. Check the first batch frame by frame before posting anything.

What makes a good campaign for new accounts: big streamer, hot game, lots of
live hours, **low minimum views per video and low payout threshold**.

## Campaign records

### Clix: $5,000 GTA VI Marathon Pool (Reach), ended ~Nov 23
- Campaign: contentrewards.com/c/campaigns/985dc674-c75e-44fc-ac87-1b1506324389,
  full rules: reachclipping.com/ClixGTA
- Pool split by each clipper's share of approved views, paid when the pool ends.
- **Minimum 500 views per video; 400,000 total views minimum to get paid.**
- Footage from his GTA marathon (from Nov 18, 2026); Clix must be the main subject.
- Mention Clix in caption or text overlay **and** use #Clix.
- Submit each clip link within **30 minutes** of posting.
- 50%+ of viewers from English-speaking countries (US, CA, AU, UK, NZ).
- No AI-generated video, **no logos**. One strike = removed from all Reach
  campaigns permanently.
- Platforms: TikTok, Instagram (Business/Creator account confirmed OK), YouTube, X.

### SypherPK: $7,500 Clipping Campaign (Reach), skipped
- $2 per 1K views (TikTok, Instagram, YouTube, X); payout starts at **10,000
  views** per video; $20 min, $500 max payout.
- Only VODs of the Nov 15 stream by Sypher, Replays or Maddynf; all 3 playing
  together must be the focus.
- Caption must include #fortnitecreative #uefn and a creator name; English only;
  nothing negative about the creators / Fortnite / Epic / UEFN; no hate farming,
  no AI, no logos, no botting, no reposts/collab posts; account niche must fit.

## Platform lessons

- **New accounts:** warm up 1-2 days first (profile picture, bio, scroll and like
  the niche), then 1-2 posts/day for ~3 days, ramp to 3-4, then 5+.
- **Post from the phone app.** Web uploads of ~10 clips on day one = 0 views on
  TikTok. The same clip from the phone got views within an hour.
- **Instagram** flags clip accounts as "not original" (others post the same
  moments): 10 posts flagged, account hidden from non-followers until deleted.
  Use only uniquely edited clips (zoom punch-ins, own colour, progress bar),
  1-2/day. A logo would NOT fix it (fingerprinting) and breaks "no logos".
- **TikTok** "Ineligible for recommendation" hit IRL footage, a strip-club
  scene, pepper-spray footage and a Sypher repost. Avoid nudity, IRL / real
  people, violence; the account itself stayed fine.
- **YouTube:** new channels have a daily upload limit; verify by phone.
- **X:** fine for volume; 2 hashtags max; upload the video, not a link.
- Spread posts out; only post the strongest clips. Views come from a few strong
  clips, not volume.

## Known issues / history

- Batches 50-54: no webcam (Clix streamed without it). Fixed going forward with
  the per-clip webcam check; those batches were not redone.
- Batch 28 (re-edits) was slow motion on 60 fps footage. Fixed; Batch 29 is the
  good version.
- Early marathon batches (before the layout fix) had shrunk/mirrored layouts.
- Clips made: 261 total (219 Clix, 16 Sypher, 26 re-edits).
