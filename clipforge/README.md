# ClipForge: AI viral clip generator

Paste a YouTube URL and get back ranked, captioned, vertical (9:16) MP4 clips for YouTube Shorts, TikTok and Instagram Reels. Each clip is at most 60 seconds.

```
URL ─▶ metadata & access checks ─▶ download (≤1080p) ─▶ timestamped transcript
    ─▶ sentence units ─▶ moment detection (LLM or heuristics) ─▶ transparent scoring
    ─▶ dedupe & rank ─▶ FFmpeg render (reframe + captions + loudness) ─▶ dashboard / MP4 / ZIP
```

> ClipForge lives in `clipforge/` and is independent of the rest of this repository.

---

## Features

**Input.** The app accepts `youtube.com/watch`, `youtu.be`, `/shorts/`, `/live/` (finished recordings), `/embed/`, `m.` and `music.` URLs, with or without a scheme or tracking parameters. Playlist, channel and other-site URLs are rejected with a specific message. Ingestion is provider-based (`app/ingest/base.py`), so you can register other authorised sources.

**Compliance.** Only publicly accessible videos are processed:
- No cookies or logins are used.
- DRM, private, members-only, sign-in age-gated, region-locked, upcoming and in-progress live videos fail with a clear, specific error.
- The user must confirm they own the content or are authorised to use it.

**Transcripts.**
- Human captions are preferred.
- Otherwise the app uses local **faster-whisper** or the **OpenAI** transcription API.
- YouTube auto-captions are the last resort.
- Timestamps are kept at word level.

**Moment detection.** Clips are never cut into fixed 60-second chunks:
- The transcript is split into sentence units, and clip boundaries only fall on sentence boundaries, padded so the first and last syllables aren't clipped.
- Overlapping candidate windows are generated from every sentence start to every later sentence end, from 15 to 60 seconds.
- **LLM mode** (Anthropic Claude via the official SDK, or any OpenAI-compatible endpoint): the model reads a numbered, timestamped transcript and returns moments as structured JSON (unit-id ranges plus sub-scores, explanation, hook and platform copy).
  - Ids are mapped to times locally, so timestamps can't be hallucinated.
  - Hook quotes are checked against the transcript and replaced with the real first sentence if they don't match.
  - Very long transcripts are chunked with overlap.
- **Heuristic mode** (free, offline, also blended into LLM scores at 30%) scores observable features:
  - hook phrases, questions, numbers and direct address
  - emotion, laughter, story and gaming language
  - controversy, advice, facts and relatability
  - connector or pronoun openings, references to earlier content, topic changes mid-clip, outros
  - closers and punchlines, "keeps going past the punchline", two moments stitched together
  - speech rate, dead air, ideal length
  - a per-second audio-energy curve (hype and reaction spikes)

**Scoring.** The weights are hook 25%, emotion/entertainment 20%, standalone clarity 20%, payoff 15%, pacing 10% and shareability 10%. Every clip shows its sub-scores, an explanation, its verbatim hook and why it was selected. Scores are heuristic estimates, not predictions of views.

**Deduplication.** Selection is greedy and best-first. A candidate is dropped if it overlaps an already-chosen clip by more than 2 seconds, or if it repeats the same idea (content-word Jaccard similarity above 0.5).

**Editing (FFmpeg).**
- **Output.** 1080×1920 for sources of 1080p or higher (720×1280 or 540×960 for smaller ones), H.264 + AAC, `+faststart`, loudness-normalised to −14 LUFS with short fades to avoid clicks.
- **Captions.** Word-highlighted ASS captions rendered with libass. Font, size, colours, outline, position, uppercase and words per caption are all configurable.
- **Framing.**
  - **Auto**: picks one of the modes below.
  - **Speaker tracking**: OpenCV face detection. When several faces are visible, the likely speaker is chosen using mouth-motion and face size, with hysteresis so the camera doesn't jump back and forth, then smoothed with a dead-zone and gliding crop.
  - **Gaming**: full gameplay over a blurred fill, with a detected corner facecam placed on top.
  - **Blurred background**: the whole frame over a blurred copy of itself.
  - **Fixed crop**: a static 9:16 crop at an adjustable position.
- **Failure handling.** If smart framing fails, the clip is re-rendered with a blurred background automatically.
- **Duration limit.** The 60-second cap is enforced when windows are generated, when the user edits timestamps, when FFmpeg runs (`-t`), and on the finished file (ffprobe check).

**Dashboard (React + TypeScript).**
- URL validation as you type, an authorisation checkbox, and clip, framing and caption settings.
- A progress stepper while a job runs.
- Source title and thumbnail, plus which transcript source and analyser were used.
- Filters: sort (score, video order, length), length buckets, minimum score, content type.
- Each clip has a 9:16 preview player, rank and score, a score breakdown, its source timestamps (linked to YouTube at that time), editable start and end (with ±½s nudges), a subtitle editor, a per-clip style and framing editor, regenerate, delete, and MP4 download.
- Suggested titles, descriptions and hashtags per platform, with copy buttons.
- Download all clips as a ZIP, which also includes `clips.txt` with each clip's metadata.

**Jobs.** Jobs run on a background thread pool and are saved as JSON on disk.
- Progress is reported by stage.
- Retries use backoff for transient network, API and download errors.
- Jobs can be cancelled or retried.
- Jobs interrupted by a server restart are marked as failed.
- Retention cleanup runs at startup and via `POST /api/cleanup`.

**Demo mode.** A clearly labelled, locally generated sample video (a test card with no real footage or speech) and a scripted sample transcript. The real analysis and rendering pipeline runs on it, so the UI can be tried with no network or keys. The UI marks it as **DEMO / SAMPLE** everywhere and says no real video was processed.

---

## Setup

Requirements: **Python 3.10+**, **Node 18+**, **FFmpeg** (with libass and libx264; standard distro builds have both).

```bash
# 1. FFmpeg
sudo apt install ffmpeg        # macOS: brew install ffmpeg   Windows: winget install ffmpeg

# 2. Backend
cd clipforge/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# optional: local speech-to-text and/or S3 storage
pip install -r requirements-optional.txt
cp .env.example .env           # then add keys if you want LLM analysis / OpenAI STT
uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd clipforge/frontend
npm install
npm run dev                    # http://localhost:5173 (proxies /api to :8000)
```

**Single-process / production:** run `npm run build` in `frontend/`. FastAPI then serves `frontend/dist` at `/`, so `uvicorn app.main:app --host 0.0.0.0 --port 8000` serves the whole app.

**Docker:** `docker build -t clipforge clipforge/ && docker run -p 8000:8000 -v clipforge-data:/data --env-file clipforge/backend/.env clipforge`

### Environment variables

See [`backend/.env.example`](backend/.env.example) for every option. The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `ANALYSIS_PROVIDER` | `auto` | `anthropic`, `openai`, `heuristic`, or `auto` (first key found, else heuristic) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_EFFORT` | – / `claude-opus-5-5` / `medium` | Claude moment analysis (structured outputs) |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | – | OpenAI or any compatible server (Ollama, vLLM…) for analysis; OpenAI also for STT |
| `TRANSCRIPTION_PROVIDER` | `auto` | `youtube_captions`, `faster_whisper`, `openai` or `auto` |
| `WHISPER_MODEL` | `small` | faster-whisper model size |
| `MAX_VIDEO_SECONDS` | `0` (no limit) | Reject sources longer than this |
| `RETENTION_HOURS` | `48` | Auto-delete finished jobs older than this |
| `STORAGE_BACKEND` | `local` | `local` or `s3` (`S3_BUCKET`, AWS credentials) |
| `WORKER_THREADS` | `2` | Concurrent jobs and clip renders |

API keys are read only by the server. `/api/config` reports *whether* a key is set, never its value (there is a test for this).

### Costs

All of these are optional. The app works with no paid service at all, using platform captions or local faster-whisper together with heuristic analysis.

- **Claude (`claude-opus-5-5`)**: $4 per million input tokens and $20 per million output tokens. One hour of speech is roughly 15k transcript words, which comes to about 25–35k input tokens with timestamps. The structured output plus reasoning is typically 10–20k tokens. **Rough estimate: ~$0.30–$0.60 per hour of source video** at `ANTHROPIC_EFFORT=medium`. Lowering the effort or switching to `ANTHROPIC_MODEL=claude-sonnet-5-5` ($2/$10) or `claude-haiku-5-5` ($0.10/$0.50) costs less.
- **OpenAI `whisper-1` STT**: about $0.006 per audio minute (~$0.36/hour).
- **faster-whisper**: free, runs locally. CPU is roughly real-time or faster with the `small` model; a GPU is much faster.

---

## Tests

```bash
cd clipforge/backend && python -m pytest          # ~2–3 min, includes real FFmpeg renders and a full demo run
python -m pytest -m "not slow"                    # skip the end-to-end demo render
cd ../frontend && npm run typecheck && npm run build
```

What the tests cover:
- **URL validation**: every supported form plus rejection cases, and the mapping from yt-dlp errors to user-facing messages.
- **Caption parsing**: YouTube json3, manual VTT, and rolling auto-caption VTT.
- **Units and windows**: sentence segmentation, window generation and boundaries, the ≤60s limit, and never spanning long silences.
- **Scoring and selection**: the scoring weights, heuristic rankings, deduplication, and the detector with a mocked LLM (quote verification, id clamping, fallback when the LLM fails).
- **Anthropic SDK request shape**: checked through the real SDK against a mock HTTP transport.
- **Captions and reframing**: ASS output, caption grouping and editing, face-track planning and speaker hysteresis, facecam detection.
- **Real FFmpeg**: renders in every layout, the >60s cap, video without audio, and the loudness curve.
- **API end to end**: demo job → MP4s → Range requests → timestamp and caption edits → ZIP → delete, plus the error path for an inaccessible YouTube video.

---

## Status: what's verified and what isn't

Verified in the development sandbox:
- The full pipeline in demo mode: analysis, scoring, captions, all framing layouts, MP4 output, ZIP, editing and regeneration (`88+` tests passing).
- Every frontend screen in Chromium, at desktop and mobile widths.

**Not verified there:**
- **Live YouTube ingestion.** The sandbox's network blocks youtube.com, so yt-dlp download and caption fetching were not exercised against real videos. The code uses yt-dlp's documented API, and the error mapping is unit-tested. Verify on a machine with internet access before relying on it. YouTube changes frequently, so keep `yt-dlp` updated (`pip install -U yt-dlp`). Some networks (for example datacenter IPs) get YouTube "confirm you're not a bot" checks; ClipForge reports that error clearly rather than working around it.
- **Live LLM and STT calls.** No API keys were available. The Anthropic request is checked through the real SDK against a mock transport, but the live API was not called. The OpenAI-compatible analyser, OpenAI STT and faster-whisper were not run (Hugging Face model downloads were also blocked).
- **Face tracking on real footage.** The tracking maths and the FFmpeg crop expression are tested, but OpenCV detection was only run on synthetic frames, which contain no faces. Speaker detection is a lightweight mouth-motion heuristic, not an audio-visual active-speaker model.
- **S3 storage and the Docker image** were not built or exercised here.

## Layout

```
clipforge/
  backend/app/
    main.py            FastAPI routes (jobs, clips, downloads, cleanup, static UI)
    pipeline.py        job orchestration, rendering, edits
    jobs.py            JSON job store + worker pool
    ingest/            URL validation, provider interface, YouTube (yt-dlp)
    transcribe/        caption parsers, STT providers, strategy
    analysis/          sentence units, candidates, heuristic scorer, LLM layer, selection, copywriting
    video/             ffmpeg wrappers, ASS captions, reframing, renderer
    demo.py            labelled sample assets
    storage.py         local / S3 adapters
  backend/tests/
  frontend/src/        React + TypeScript dashboard
```
