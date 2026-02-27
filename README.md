# korede-short-api

An autonomous media generation API that turns text prompts and narration scripts into fully assembled short-form videos. Designed to run as a backend service for n8n automation workflows or any HTTP client.

---

## How It Works

Each render job takes a list of scenes. For every scene the pipeline:

1. **Generates an image** from the `image_prompt` via Kie.ai (Flux-2 Pro)
2. **Generates a voiceover** from the `narration_text` via ElevenLabs (routed through Kie.ai)
3. **Creates a video clip** — either a Ken Burns motion effect (static image) or an AI animation (ByteDance image-to-video)
4. **Assembles the scene** — syncs video to the exact audio length, burns subtitles
5. **Concatenates all scenes** into a final video, optionally mixing in background music
6. **Uploads everything to S3** and fires a webhook when done

All heavy processing runs in Celery workers, so the API returns immediately with a job ID and you poll for status.

---

## Channels

| Channel | Description |
|---------|-------------|
| `kenburns` | Applies a Ken Burns pan/zoom motion to a static image. Fast, fully local (FFmpeg). |
| `animated` | Sends the image to Kie.ai's ByteDance image-to-video model to generate real animation. Slower, consumes Kie.ai credits. |

---

## Tech Stack

- **FastAPI** — async REST API, port 2000
- **Celery + Redis** — background task queue
- **PostgreSQL** — stores projects, jobs, and scene state
- **FFmpeg** — Ken Burns effects, scene assembly, audio sync, subtitles
- **Kie.ai** — image generation and image-to-video animation
- **ElevenLabs** (via Kie.ai) — text-to-speech
- **AWS S3** — stores all generated media artifacts
- **Docker Compose** — runs the full stack (API, worker, beat, DB, Redis)

---

## Prerequisites

- Docker and Docker Compose
- A Kie.ai API key
- An AWS S3 bucket with `s3:PutObject` / `s3:GetObject` permissions
- (Optional) An ElevenLabs API key if you need it independently; currently TTS is proxied through Kie.ai

---

## Setup

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd korede-short-api
cp .env.example .env
```

Edit `.env` and fill in every value:

```env
# App
API_KEY=your-secret-api-key-here
APP_ENV=production

# Database (matches docker-compose.yml defaults)
DATABASE_URL=postgresql+asyncpg://media:password@db:5432/media_master

# Redis (matches docker-compose.yml defaults)
REDIS_URL=redis://redis:6379/0

# Kie.ai
KIE_AI_API_KEY=your-kie-ai-key
KIE_AI_BASE_URL=https://api.kie.ai/api/v1

# AWS S3
S3_BUCKET=your-bucket-name
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# ElevenLabs (stored for reference; TTS is proxied via Kie.ai)
ELEVENLABS_API_KEY=your-elevenlabs-key
```

### 2. Start the stack

```bash
docker compose up -d --build
```

This starts: `api`, `celery_worker`, `celery_beat`, `db`, `redis`.

### 3. Run database migrations

```bash
docker compose exec api alembic -c alembic/alembic.ini upgrade head
```

### 4. Verify health

```bash
curl http://localhost:2000/api/v1/health
```

Expected:
```json
{
  "status": "healthy",
  "checks": {
    "ffmpeg": { "status": "ok" },
    "redis":  { "status": "ok" },
    "database": { "status": "ok" }
  }
}
```

---

## API Reference

All endpoints except `/health` require an API key header:

```
api-key: your-secret-api-key-here
```

Interactive docs are available at `http://localhost:2000/docs`.

---

### Start a Render Job

```
POST /api/v1/render
```

**Body:**

```json
{
  "project_name": "My Video Project",
  "channel": "kenburns",
  "webhook_url": "https://your-server.com/webhook",
  "settings": {
    "aspect_ratio": "16:9",
    "resolution": "1K",
    "fps": 30,
    "subtitle_enabled": true,
    "subtitle_style": "bold_center",
    "transition_type": "cut",
    "background_music": "https://example.com/music.mp3",
    "background_music_volume": 0.15
  },
  "scenes": [
    {
      "scene_number": 1,
      "image_prompt": "A serene mountain landscape at golden hour",
      "narration_text": "Every great journey begins with a single step.",
      "voice_id": "EXAVITQu4vr4xnSDxMaL",
      "pan_direction": "right",
      "ken_burns_keypoints": [
        { "x": 30, "y": 50, "zoom": 1.0 },
        { "x": 60, "y": 40, "zoom": 1.3 },
        { "x": 80, "y": 55, "zoom": 1.5 }
      ]
    },
    {
      "scene_number": 2,
      "image_prompt": "A busy city street at night with neon lights",
      "narration_text": "The city never sleeps, always alive with possibility.",
      "voice_id": "EXAVITQu4vr4xnSDxMaL"
    }
  ]
}
```

**Response `202`:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "total_scenes": 2,
  "monitor_url": "/api/v1/render/550e8400-e29b-41d4-a716-446655440000/status",
  "message": "Render job queued successfully"
}
```

---

### Settings Reference

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `aspect_ratio` | string | `"16:9"` | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"` |
| `resolution` | string | `"1K"` | `"1K"`, `"2K"`, `"4K"` — used by Kie.ai image generation |
| `fps` | int | `30` | Frames per second for Ken Burns output |
| `subtitle_enabled` | bool | `true` | Burn subtitles into video |
| `subtitle_style` | string | `"bold_center"` | `"bold_center"`, `"bottom_bar"`, `"minimal"` |
| `transition_type` | string | `"cut"` | `"cut"` (hard cut) or `"crossfade"` |
| `transition_duration_ms` | int | `500` | Transition overlap in milliseconds |
| `background_music` | string | `null` | HTTP URL or S3 key for a music file |
| `background_music_volume` | float | `0.15` | `0.0` – `1.0` |

---

### Scene Reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `scene_number` | int | Yes | 1-based, sets scene order |
| `image_prompt` | string | Yes | Text prompt for image generation |
| `narration_text` | string | Yes | Text to convert to speech |
| `voice_id` | string | Yes | ElevenLabs voice ID |
| `animation_prompt` | string | No | Only used when `channel = "animated"`. Defaults to `image_prompt`. |
| `pan_direction` | string | No | `"right"`, `"left"`, `"up"`, `"down"`, `"zoom_in"`, `"zoom_out"` — used when no keypoints are provided |
| `ken_burns_keypoints` | array | No | Explicit motion path. Takes priority over `pan_direction`. Minimum 2 points. |

**Ken Burns Keypoint:**

```json
{ "x": 50, "y": 40, "zoom": 1.2 }
```

| Field | Range | Description |
|-------|-------|-------------|
| `x` | 0–100 | Focal point X as % of image width |
| `y` | 0–100 | Focal point Y as % of image height |
| `zoom` | 1.0–4.0 | Zoom factor (1.0 = no zoom, 2.0 = 2× zoom) |

The camera smoothly interpolates through all keypoints over the duration of the scene's audio.

If no keypoints and no `pan_direction` are provided, the system auto-assigns a direction cycling through `right → left → zoom_in → up → down → zoom_out` by scene number.

---

### Check Job Status

```
GET /api/v1/render/{job_id}/status
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "channel": "kenburns",
  "progress": {
    "total_scenes": 2,
    "completed_scenes": 1,
    "failed_scenes": 0,
    "percentage": 50.0
  },
  "final_video_url": null,
  "estimated_completion_minutes": 0.2,
  "scenes": [
    {
      "scene_number": 1,
      "status": "completed",
      "assembled_scene_url": "https://..."
    },
    {
      "scene_number": 2,
      "status": "assembling",
      "assembled_scene_url": null
    }
  ]
}
```

**Job statuses:** `pending` → `processing` → `assembling` → `completed` / `partial_failure` / `failed`

**Scene statuses:** `pending` → `generating_image` → `generating_voice` → `animating` / `applying_effects` → `assembling` → `completed` / `failed`

---

### Retry Failed Scenes

```
POST /api/v1/render/{job_id}/retry
```

```json
{ "retry_all_failed": true }
```

or retry specific scenes:

```json
{ "scene_numbers": [2, 5] }
```

---

### Cancel a Job

```
POST /api/v1/render/{job_id}/cancel
```

---

## Webhooks

If `webhook_url` is set, the API sends a `POST` to that URL when the job finishes.

**Completion:**
```json
{
  "event": "render_completed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "final_video_url": "https://your-bucket.s3.amazonaws.com/media-master/.../final_output.mp4",
  "completed_at": "2024-02-27T10:15:00Z"
}
```

**Failure:**
```json
{
  "event": "render_failed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error_message": "Too many scenes failed (4/5). Below 50% threshold.",
  "failed_scene_numbers": [1, 3, 4, 5],
  "completed_at": "2024-02-27T10:15:00Z"
}
```

---

## S3 Storage Layout

```
s3://your-bucket/
  media-master/
    {project_id}/
      {job_id}/
        images/      — generated images (PNG)
        voices/      — generated audio (MP3)
        animations/  — raw video clips (MP4)
        scenes/      — assembled scenes with audio + subtitles (MP4)
        final/       — final_output.mp4
```

---

## Viewing Logs

```bash
# API logs
docker compose logs -f api

# Worker logs (pipeline progress, errors)
docker compose logs -f celery_worker

# Follow a specific job
docker compose logs -f celery_worker | grep "job_id=550e8400"
```

---

## Updating the Server

```bash
git pull
docker compose up -d --build

# Run any new migrations
docker compose exec api alembic -c alembic/alembic.ini upgrade head
```

---

## Configuration Reference

All settings are read from `.env` (or environment variables).

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | — | Secret key for all API requests |
| `APP_ENV` | `production` | `development` enables SQL query logging |
| `APP_PORT` | `2000` | Port the API listens on |
| `DATABASE_URL` | — | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `KIE_AI_API_KEY` | — | Kie.ai API key |
| `KIE_AI_BASE_URL` | `https://api.kie.ai/api/v1` | Kie.ai base URL |
| `KIE_AI_CONCURRENCY` | `5` | Max parallel Kie.ai requests |
| `ELEVENLABS_CONCURRENCY` | `5` | Max parallel TTS requests |
| `S3_BUCKET` | — | S3 bucket name |
| `S3_REGION` | `us-east-1` | AWS region |
| `AWS_ACCESS_KEY_ID` | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | — | AWS credentials |
| `BATCH_SIZE` | `10` | Scenes processed in parallel per batch |
| `SCENE_FAILURE_THRESHOLD` | `0.5` | Minimum % of scenes that must succeed |
| `TEMP_DIR` | `/tmp/media-master` | Local scratch space for FFmpeg |
| `FFMPEG_PATH` | `/usr/bin/ffmpeg` | Path to FFmpeg binary |
| `FFPROBE_PATH` | `/usr/bin/ffprobe` | Path to FFprobe binary |
