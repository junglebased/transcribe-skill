# SPEC — Meeting capture → Notion

Status: shaping (waiting for approach choice) · Date: 2026-10-11

## Goal
Transkriptor-style meeting notes for Google Meet and Zoom: capture the call, transcribe it,
and save a Notion page with Title, Date, Platform, Participants, Duration, Summary,
Action items, Transcript (page body) and Recording link.

Hard constraint: **free** (no per-hour fees, no paid server).

## Appetite
~1 working day for v1. If a bot needs more than that to join reliably, it is out of v1.

## Options compared

| | A. Local capture (no bot) | B. Self-hosted bot (Attendee / Vexa) | C. Recall.ai |
|---|---|---|---|
| Cost | 0 | 0 software; needs an always-on machine/server (Mac + Docker = 0, VPS ≈ $5–20/mo) | $0.50/rec-hour + $0.15 transcription; only first 5 h free |
| Setup | `brew install ffmpeg` (+ optional BlackHole) or a small Swift audio-tap helper; Notion token | Docker + Postgres + Redis; Zoom Marketplace "General App" with Meeting SDK (Client ID/Secret); Google account for Meet bot; Attendee's Zoom path expects Deepgram (free 400 h credit) or custom STT | API key; Zoom/Meet bot handled by vendor |
| Joins without you | No — you start/stop (or calendar-triggered) on your Mac | Yes, via meeting URL (calendar auto-join needs Google Calendar access + scheduler) | Yes |
| Host friction | None; nobody sees a bot | Bot waits in lobby, host must admit; Zoom host may need to allow external recording; Meet blocks bots more often | Same lobby issues, vendor-handled |
| Speakers | No real diarization from one mixed track; "Me" (mic) vs "Others" (system audio) if recorded as 2 channels | Per-participant names from the platform (speaker timeline) | Per-participant |
| Transcription | Existing local mlx-whisper (free, offline) | Can feed recording to local mlx-whisper after the call | Paid or own |
| Reliability | High (no third-party UI scraping); depends on you pressing start | Medium: Meet bot drives headless Chrome, breaks when Google changes UI; Zoom SDK needs app review for others' meetings | High |
| Privacy | Fully local | Self-hosted, local | Vendor cloud |

Evidence:
- Attendee: single Docker image (Django) + Postgres + Redis; Zoom needs own Zoom app with Meeting SDK; Meet bot runs full Chrome, heavier — [repo](https://github.com/attendee-labs/attendee), [docs](https://www.mintlify.com/attendee-labs/attendee/quickstart), [FAQ](https://www.mintlify.com/attendee-labs/attendee/guides/faq).
- Vexa: Apache-2.0, Meet + Teams + Zoom; Zoom Meeting SDK support marked initial/pre-release and needs Zoom app approval — [repo](https://github.com/Vexa-ai/vexa).
- Recall.ai: $0.50/h PAYG, $0.15/h transcription, first 5 h free, no permanent free tier — [pricing](https://www.recall.ai/pricing), [2026 pricing post](https://recall.ai/blog/new-recall-ai-pricing-for-2026).

Existing prototype (Lab, `meet-rec`): 20-line zsh script — `start` runs ffmpeg avfoundation on one input
device into `~/Meetings/<date>/rec.m4a`, `stop` runs `transcribe.py --mode plain,md`. Works for mic only;
both sides of the call need BlackHole + Aggregate device. Reused as the base of option A.

## Recommendation
**A now, B later as optional.** A is the only option that is free, reliable and done in the appetite.
Upgrade A from the prototype:
1. Record mic and system audio as **two channels** (macOS 14.4+ Core Audio process tap via small Swift
   helper, no BlackHole; BlackHole stays as fallback) → "Me / Others" speaker labels.
2. Auto-detect platform + title from the active Meet tab / Zoom window; optional Google Calendar
   lookup for title and participants.
3. Transcribe locally with existing `transcribe.py`.
4. Summary + action items written by Claude Code itself (the skill runs inside it, no API cost).
5. Push to Notion database (token in `.env`), recording kept locally, path/link in "Recording link".

B (Attendee on local Docker) can be added later behind the same Notion writer for meetings you
don't attend yourself; it costs setup time (Zoom app, Google bot account) and Meet breakage risk.

## Out of scope (v1)
- Joining meetings you are not in; bot presence in the call.
- True multi-speaker diarization (pyannote needs HF token + heavy models; maybe v2).
- Live/real-time captions. Teams, Webex.
- Hosting anything in the cloud.

## Done criteria
- `meeting start` / `meeting stop` (and skill trigger "toplantıyı kaydet") record both sides of a real
  Meet and a real Zoom call.
- After stop: local transcript (md + txt), Notion row created with all 9 fields, transcript in body.
- No secrets or personal data in repo; `.env.example` documents `NOTION_TOKEN`, `NOTION_DB_ID`.
- SKILL.md + README have a `meeting` section. Tested end-to-end on a short real call.
