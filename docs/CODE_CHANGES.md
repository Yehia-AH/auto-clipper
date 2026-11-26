# Every code change

All commits to this repo, oldest first (from `git log`).

### 2026-11-18 17:12 · Auto clipper: transcribe, pick highlights with Claude, render vertical captioned clips


### 2026-11-18 18:05 · Clip live streams: YouTube /streams and Twitch VODs, long-stream handling, gaming split layout

- Bare channel links cover uploads and past streams; Twitch channels map to VODs
- Wait until streams end and VODs are ready before clipping
- Long streams: 720p download, faster Whisper model, hour-by-hour highlight picking
- Stay inside GitHub's 6h job limit; retry failed videos up to 3 times
- Auto-detect a corner webcam and render webcam-on-top / gameplay-below


### 2026-11-18 18:21 · Add one-click setup check workflow


### 2026-11-18 18:23 · Clearer Telegram token errors; ignore stray whitespace in secrets


### 2026-11-18 18:23 · Keep deliver.py compatible with Python 3.10


### 2026-11-18 18:32 · Clip marathon streams in parts; tune config for GTA 6 gaming clips


### 2026-11-18 18:44 · Add Clix GTA and SypherPK campaigns; per-source campaign rules; clip live Twitch marathons part by part

- Sources can carry campaign rules: required name and hashtags in captions,
  moment-picking notes, optional on-screen handle, Telegram reminder
- Manual-only sources (auto: false) for campaigns tied to specific VODs
- Live Twitch marathons: clip each finished 4h part while the stream runs,
  several parts per run when time allows


### 2026-11-18 19:00 · Check hourly and clip live marathons in 1-hour parts


### 2026-11-18 19:06 · Let pasted-URL runs run in parallel; merge progress safely when runs finish together


### 2026-11-18 19:16 · Hourly runs finish long videos that a by-hand run didn't get through


### 2026-11-18 19:19 · Update processed videos


### 2026-11-18 19:20 · Decode audio with ffmpeg instead of PyAV (faster-whisper breaks on PyAV 19)


### 2026-11-18 19:27 · Unbuffered output so run logs show progress live


### 2026-11-18 19:31 · Name each run after what it does (pasted link, hourly check, or manual check)


### 2026-11-18 19:34 · Campaign dropdown when running by hand: names the run and applies that campaign's rules


### 2026-11-18 19:41 · 📭 Set up run requests (test: empty request, no clipping)


### 2026-11-18 19:48 · 📋 Test: check reports now also go to Telegram


### 2026-11-18 19:49 · Update processed videos


### 2026-11-18 19:51 · Clip live Twitch marathons as they record; campaign start dates; drop weak clips

- Twitch marks a VOD that's still recording as live: cut finished hours straight
  from its HLS playlist with ffmpeg instead of waiting for the stream to end
- since: per-source start date (Clix: 2026-11-18) so older VODs aren't clipped
- min_score (6): don't send moments Claude rates as weak


### 2026-11-18 19:54 · Update processed videos


### 2026-11-18 19:56 · 🔎 Clix: marathon check now [watched]


### 2026-11-18 20:10 · Better gaming framing (any small webcam -> split, keep cam out of gameplay) and hype detection from audio energy


### 2026-11-18 20:10 · ✂️ SypherPK: re-run with new framing + hype detection


### 2026-11-18 20:14 · Update processed videos


### 2026-11-18 20:16 · Telegram delivery retries and never crashes a run (connection reset lost run #6's progress)


### 2026-11-18 20:22 · Chat spike detection: Twitch chat replay rate per 10s tags each line and lists spikes for Claude (clip starts ~20s before a spike)


### 2026-11-18 20:22 · 🔎 Clix: marathon with chat spikes + new layout [watched]


### 2026-11-18 20:30 · GTA event cues (from ColinGPT9's MIT GTA plugin) and 'clip it' chat nominations as signals for Claude


### 2026-11-18 20:56 · Fix: every stream part gets its own folder (long titles made all marathon hours share hour 1's transcript -> captions didn't match clips)


### 2026-11-18 20:58 · Update processed videos


### 2026-11-18 20:59 · 🔎 Clix: redo marathon from hour 2 with matching captions [watched]


### 2026-11-18 21:00 · 🔎 Clix: redo marathon from hour 2 with matching captions [watched]


### 2026-11-18 21:41 · Chain runs while a marathon still has finished hours to clip (hourly schedule has been skipping)


### 2026-11-18 22:00 · Number every batch and clip (Batch N, clip N.i) in Telegram, files and releases


### 2026-11-18 23:02 · QA fixes: progress keyed by one id + no-repeat safety net; cap bitrate so clips stay under Telegram's 50 MB


### 2026-11-18 23:39 · Self-sustaining runs during live marathons (GitHub's hourly schedule isn't firing)


### 2026-11-18 23:39 · Give up on a stream part after 3 failures so runs don't keep retrying it


### 2026-11-18 23:51 · Only 8/10+ clips, max 3 per stream hour; daily top-picks message; stop watching a one-off marathon once fully clipped


### 2026-11-18 23:57 · Update processed videos


### 2026-11-18 23:59 · 🔎 Clix: continue marathon from hour 14 (new filters) [watched]


### 2026-11-18 23:59 · GTA 6 check: Claude looks at 3 frames per clip and drops IRL / chatting / other-game moments for Clix


### 2026-11-19 00:02 · Clix: clip all marathon moments again (GTA 6-only check switched off, kept as an option)


### 2026-11-19 01:01 · Update processed videos


### 2026-11-19 01:39 · Detect tiny corner webcams (Clix) for the split layout; zoom into gameplay instead of shrinking it when there's no webcam


### 2026-11-19 01:41 · IRL / full-camera footage: one face-following crop instead of a doubled split


### 2026-11-19 01:41 · Re-make specific hours of a long stream (parts=2-13) without touching live progress


### 2026-11-19 01:41 · ✂️ Clix: re-make hours 2-7 in the new layout


### 2026-11-19 01:42 · ✂️ Clix: re-make hours 8-13 in the new layout


### 2026-11-19 01:56 · Switch clip picking to Claude Haiku 5.5 (~40x cheaper); no server-side fallback on Haiku


### 2026-11-19 02:01 · Update processed videos


### 2026-11-19 02:01 · Update processed videos


### 2026-11-19 02:10 · Clix: fixed webcam box (top-left) for the split layout, so his webcam always shows; IRL still gets the face-following crop


### 2026-11-19 02:51 · Clix: GTA 6 gameplay only (frame check on)


### 2026-11-19 02:51 · ✂️ Clix: re-make gameplay hours 3-7 (new layout, GTA only, Haiku)


### 2026-11-19 02:51 · ✂️ Clix: re-make gameplay hours 9-9 (new layout, GTA only, Haiku)


### 2026-11-19 02:59 · Update processed videos


### 2026-11-19 03:04 · Better clips: 1080p downloads, Opus picks the moments, Haiku does a looser 'is this gameplay?' check


### 2026-11-19 03:04 · ✂️ Clix: re-make gameplay hours 3-4 (1080p, Opus, gameplay check)


### 2026-11-19 03:04 · ✂️ Clix: re-make gameplay hours 5-7 (1080p, Opus, gameplay check)


### 2026-11-19 03:05 · ✂️ Clix: re-make gameplay hours 9-9 (1080p, Opus, gameplay check)


### 2026-11-19 03:15 · Update processed videos


### 2026-11-19 03:19 · Update processed videos


### 2026-11-19 03:34 · Update processed videos


### 2026-11-19 03:46 · Update processed videos


### 2026-11-19 07:45 · Update processed videos


### 2026-11-19 08:35 · Update processed videos


### 2026-11-19 09:22 · Update processed videos


### 2026-11-19 10:04 · Update processed videos


### 2026-11-19 10:30 · 45-min limit on every download (a stuck one ate run #12's 6 hours); log what's being downloaded; timeouts retry next run


### 2026-11-19 10:41 · Telegram gets each clip's size so it isn't shown squashed; Clix (gameplay-only) always uses webcam-on-top


### 2026-11-19 12:09 · Find one specific moment by description (find=...) and clip just that


### 2026-11-19 12:09 · 🔍 Clix: find 'fixing a pipe, lady walks in' (hour 1)


### 2026-11-19 12:09 · 🔍 Clix: find 'fixing a pipe, lady walks in' (hour 2)


### 2026-11-19 12:20 · Update processed videos


### 2026-11-19 12:49 · 🔍 Clix: find plumbing scene + bikini walk-in reaction (hour 2)


### 2026-11-19 12:50 · 🔍 Clix: find plumbing scene + bikini walk-in reaction (hour 3)


### 2026-11-19 12:58 · Update processed videos


### 2026-11-19 15:05 · SypherPK: required #fortnitecreative #uefn in every caption; campaign rules in the moment-picking notes


### 2026-11-19 15:23 · Update processed videos


### 2026-11-19 15:46 · Live recorder: record Twitch streams while live and clip every hour

- live.yml checks every 10 min; when a live: true streamer is on, one run records
  ~3-4 h (split at each stream hour), clips each finished hour, then hands off to
  the next run at the hour boundary. Reconnects on drops, stops when the stream ends.
- Hourly runs skip the live broadcast itself (that caused the 'Conversion failed'
  errors) and skip VODs of streams that were already recorded live.
- Clix: live: true instead of single_stream, so he's followed after the marathon.
- Shared scripts for publishing releases and saving progress.


### 2026-11-19 15:53 · Update processed videos


### 2026-11-19 15:55 · Live recorder: start a check now (and allow starting one via requests/live.txt)


### 2026-11-19 15:56 · Update processed videos


### 2026-11-19 16:40 · Update processed videos


### 2026-11-19 16:58 · Update processed videos


### 2026-11-19 17:12 · Update processed videos


### 2026-11-19 17:14 · Better clip picking (ideas from top clipping repos), live chat, skip breaks

- Moment picking uses a harsh 4-point rubric (zero context, strong first second,
  payoff, natural length) with score penalties, a trending/drama boost and
  variety, as in the ai-stream-clipper skill and Clips Kitty's scoring prompt.
- Rerank pass: candidates are ordered against each other before the best are
  kept (relative judgment beats per-clip scores that cluster at 7-9).
- Live recordings read Twitch chat anonymously while recording: chat spikes,
  'clip it' votes and what chat felt (laughing, hyped, shocked, scared, fail).
- Hours where the streamer is on a break (asleep, BRB, hardly talking) are
  skipped quietly; a recording with no audio track no longer errors.
- Live: each hour's clips are published as a release right away.
- 4 clips per hour, keep 7/10 and up (7 = strong on the stricter rubric).


### 2026-11-19 17:18 · Clip anything interesting: gameplay, reactions, chat, the streamer; 3 per hour

- Loud stretches with no talking (crash, explosion, gunfight, chase) are marked in
  the transcript so Claude can clip gameplay moments, not only speech.
- A clip can open on that gameplay before anyone speaks (up to 10 s lead-in).
- Prompt lists every kind of clip-worthy moment and favours ones that combine
  two (crazy gameplay + big reaction, funny line + chat exploding).
- Back to 3 clips per hour.


### 2026-11-19 17:39 · Update processed videos


### 2026-11-19 17:39 · Live recorder: restart with the new clip picking


### 2026-11-19 17:40 · Update processed videos


### 2026-11-19 17:40 · Clip game discoveries: glitches, easter eggs, secrets, hidden details

- The prompt ranks new-game discoveries high and starts the clip just before
  the streamer notices.
- New 'discovery' cue in the GTA event tagger for spoken glitch / easter egg /
  hidden detail lines.


### 2026-11-19 17:43 · Live recorder: restart with glitch / easter egg clipping


### 2026-11-19 17:44 · Update processed videos


### 2026-11-19 17:51 · Cut hours from a still-live Twitch recording in minutes, not real time

ffmpeg read a growing (live) playlist at playback speed, so cutting an hour hit
the 45 min limit. Now only the segments in that hour are put in a finished
playlist and fetched directly. Hand-picked re-makes (parts=) may also fill hours
of a stream the live recorder missed.


### 2026-11-19 17:51 · ✂️ Clix: today's stream, hour 1 (missed by the live recorder)


### 2026-11-19 17:51 · ✂️ Clix: today's stream, hour 3 (lost in the restart)


### 2026-11-19 17:51 · 🔎 Restart Auto Clip [watched]


### 2026-11-19 17:53 · Update processed videos


### 2026-11-19 18:22 · Fix cutting from a live Twitch recording on newer ffmpeg


### 2026-11-19 18:23 · ✂️ Clix: today's stream, hour 1 (retry)


### 2026-11-19 18:23 · ✂️ Clix: today's stream, hour 3 (retry)


### 2026-11-19 18:32 · Update processed videos


### 2026-11-19 18:33 · Update processed videos


### 2026-11-19 18:34 · Unique batch numbers across parallel runs; mask swears in captions

- A new batch number is claimed on GitHub the moment it's taken, so the live
  recorder and re-made hours running at the same time can't both use 'Batch 13'.
- Burned-in captions mask swear words (F*CK), as stream clipping tools do by
  default: platforms can limit reach for visible profanity. Audio unchanged.


### 2026-11-19 18:58 · Update processed videos


### 2026-11-19 19:59 · Update processed videos


### 2026-11-19 20:48 · Update processed videos


### 2026-11-19 20:57 · Update processed videos


### 2026-11-19 21:26 · Back to 4 clips per stream hour


### 2026-11-19 21:55 · Hook-style captions and a ready X caption for every clip

- Captions tease the payoff like a fan repost instead of describing the clip.
- Every clip also gets a one-line X/Twitter caption (2 hashtags) in Telegram.
- The streamer's name is added at the end when missing, so the hook stays first.


### 2026-11-19 21:59 · Update processed videos


### 2026-11-19 21:59 · Update processed videos


### 2026-11-19 22:00 · On-screen title is a teasing hook too, not a description


### 2026-11-19 22:01 · No emoji in on-screen titles (the font can't draw them); mask swears there too


### 2026-11-19 23:00 · Update processed videos


### 2026-11-19 23:00 · Update processed videos


### 2026-11-20 00:00 · Update processed videos


### 2026-11-20 00:00 · Update processed videos


### 2026-11-20 00:48 · Update processed videos


### 2026-11-20 01:04 · Update processed videos


### 2026-11-20 01:04 · Update processed videos


### 2026-11-20 01:54 · Update processed videos


### 2026-11-20 01:54 · Update processed videos


### 2026-11-20 02:54 · Update processed videos


### 2026-11-20 02:54 · Update processed videos


### 2026-11-20 03:53 · Update processed videos


### 2026-11-20 03:54 · Update processed videos


### 2026-11-20 04:48 · Update processed videos


### 2026-11-20 04:54 · Update processed videos


### 2026-11-20 04:54 · Update processed videos


### 2026-11-20 05:55 · Update processed videos


### 2026-11-20 05:55 · Update processed videos


### 2026-11-20 06:57 · Update processed videos


### 2026-11-20 06:57 · Update processed videos


### 2026-11-20 07:55 · Update processed videos


### 2026-11-20 07:56 · Update processed videos


### 2026-11-20 08:48 · Update processed videos


### 2026-11-20 08:51 · Update processed videos


### 2026-11-20 08:51 · Update processed videos


### 2026-11-20 09:48 · Update processed videos


### 2026-11-20 10:49 · Update processed videos


### 2026-11-20 11:28 · Update processed videos


### 2026-11-20 11:49 · Update processed videos


### 2026-11-20 12:30 · Update processed videos


### 2026-11-20 13:09 · Make every clip visibly our own (Instagram 'not original' flags)

- Zoom punch-ins on the clip's loudest moments (reactions, crashes).
- Per-clip framing and colour grade (slight zoom, contrast, saturation, hue),
  seeded per clip so no two clips match frame for frame.
- A progress bar along the bottom.
Captions and the hook title are burned in after the zoom, so they stay steady.
unique_edits: false in config.yaml turns it off.


### 2026-11-20 14:50 · Re-edit existing clips with the new look; start with 14 Clix clips

clipper/reedit.py finds each clip's exact moment in the Twitch VOD by matching its
audio (FFT cross-correlation), cuts that moment again and renders it with the
current edits (zoom punch-ins, per-clip colour, progress bar, hook captions).
Started by committing requests/reedit.json.


### 2026-11-20 14:51 · Update processed videos


### 2026-11-20 15:01 · Update processed videos


### 2026-11-20 15:03 · Fix slow motion with the unique edits on 60 fps streams; redo the re-edits

zoompan emits one frame per input frame, so 60 fps footage played at half speed
and the clip length cut it off: slow motion, out of sync with the audio. The
footage is now converted to 30 fps before zooming (checked on a 60 fps source).
Re-edit matches below 100 are rejected (muted VOD audio / wrong spot); the two
low matches (19.1, 21.4) are left out.


### 2026-11-20 15:04 · Update processed videos


### 2026-11-20 15:14 · Update processed videos


### 2026-11-20 20:22 · Update processed videos


### 2026-11-20 20:30 · Update processed videos


### 2026-11-20 20:33 · Update processed videos


### 2026-11-20 20:43 · Update processed videos


### 2026-11-20 20:54 · Update processed videos


### 2026-11-20 21:11 · Update processed videos


### 2026-11-20 21:12 · Update processed videos


### 2026-11-20 21:13 · Update processed videos


### 2026-11-20 21:34 · Update processed videos


### 2026-11-20 21:34 · Update processed videos


### 2026-11-20 22:32 · Update processed videos


### 2026-11-20 22:33 · Update processed videos


### 2026-11-20 23:33 · Update processed videos


### 2026-11-20 23:34 · Update processed videos


### 2026-11-21 00:25 · Update processed videos


### 2026-11-21 00:33 · Update processed videos


### 2026-11-21 00:33 · Update processed videos


### 2026-11-21 01:38 · Update processed videos


### 2026-11-21 01:38 · Update processed videos


### 2026-11-21 02:38 · Update processed videos


### 2026-11-21 02:39 · Update processed videos


### 2026-11-21 03:33 · Update processed videos


### 2026-11-21 03:33 · Update processed videos


### 2026-11-21 04:25 · Update processed videos


### 2026-11-21 04:36 · Update processed videos


### 2026-11-21 04:36 · Update processed videos


### 2026-11-21 05:29 · Update processed videos


### 2026-11-21 05:29 · Update processed videos


### 2026-11-21 06:31 · Update processed videos


### 2026-11-21 06:31 · Update processed videos


### 2026-11-21 07:33 · Update processed videos


### 2026-11-21 07:33 · Update processed videos


### 2026-11-21 08:24 · Update processed videos


### 2026-11-21 08:32 · Update processed videos


### 2026-11-21 08:32 · Update processed videos


### 2026-11-21 09:30 · Update processed videos


### 2026-11-21 09:30 · Update processed videos


### 2026-11-21 09:44 · Update processed videos


### 2026-11-21 10:26 · Update processed videos


### 2026-11-21 11:25 · Update processed videos


### 2026-11-21 12:25 · Update processed videos


### 2026-11-21 12:25 · Update processed videos


### 2026-11-21 13:25 · Update processed videos


### 2026-11-21 14:25 · Update processed videos


### 2026-11-21 15:25 · Update processed videos


### 2026-11-21 16:24 · Update processed videos


### 2026-11-21 16:25 · Update processed videos


### 2026-11-21 17:28 · Update processed videos


### 2026-11-21 17:28 · Update processed videos


### 2026-11-21 18:34 · Update processed videos


### 2026-11-21 18:35 · Update processed videos


### 2026-11-21 19:36 · Update processed videos


### 2026-11-21 20:25 · Update processed videos


### 2026-11-21 20:39 · Update processed videos


### 2026-11-21 21:36 · Update processed videos


### 2026-11-21 22:33 · Update processed videos


### 2026-11-21 23:10 · Update processed videos


### 2026-11-21 23:25 · Update processed videos


### 2026-11-21 23:33 · Update processed videos


### 2026-11-21 23:33 · Update processed videos


### 2026-11-22 00:32 · Update processed videos


### 2026-11-22 00:32 · Update processed videos


### 2026-11-22 01:36 · Update processed videos


### 2026-11-22 01:36 · Update processed videos


### 2026-11-22 02:33 · Update processed videos


### 2026-11-22 02:33 · Update processed videos


### 2026-11-22 02:42 · Update processed videos


### 2026-11-22 02:42 · Update processed videos


### 2026-11-22 11:13 · Update processed videos


### 2026-11-23 00:30 · Live recorder: watcher checks every 5 minutes instead of relying on GitHub's schedule

GitHub ran the */10 schedule only every 5-8 hours, so a new stream could be missed
for hours. Now a watcher run checks every 5 minutes for ~5 h and starts the next
watcher; when someone is live it starts a recording run (record=1). When a stream
ends, the recording run starts a watcher again. The schedule stays as a backup
that restarts the chain if it ever breaks.


### 2026-11-23 00:41 · Skip non-GTA hours before calling Claude (Twitch category check)

The live recorder notes the stream's Twitch category every 5 minutes (free, no
Claude). An hour where less than 20% of the samples match the source's
require_game (e.g. Fortnite before GTA 6) is skipped before transcription and
any Claude call, with a short Telegram note. Mixed hours and hours with no
category info are clipped as before.


### 2026-11-23 01:01 · Pick moments with Sonnet 5.5, rank candidates with Haiku 5.5 (lower API cost)

Sonnet 5.5 is half Opus 5.5's per-token price and keeps the refusal fallback;
the rerank step (a handful of short candidates) uses the cheap check model.


### 2026-11-23 15:03 · Pause switch (paused: true): Clix campaign pool ended

While paused nothing watches, records, clips or calls Claude, and the watcher
stops starting new watchers. Set paused: false in config.yaml to resume.


### 2026-11-24 14:37 · Check the webcam is really there before using the webcam layout

A known webcam spot can be empty (streaming without a camera, or the camera
moved), which put a random corner of the game in the top panel (batches 50-54).
Before a split render, Haiku looks at 3 crops of the webcam spot; if there's no
real person on camera, a gameplay-only campaign uses the full gameplay layout
instead. About /bin/bash.0005 per clip; errors keep the old behaviour.


### 2026-11-26 20:22 · Add PLAYBOOK.md: how the bot runs, settings, costs, campaign rules, platform lessons


