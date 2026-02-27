# Autonomous Media Generation API — Full Architectural Prompt

## Project Overview

Build a self-hosted **Media Generation API** (Python/FastAPI) that receives structured scene data from an n8n automation workflow and autonomously produces fully assembled videos. The API orchestrates multiple external AI services (Kie.ai for image/video generation, ElevenLabs for TTS), uses FFmpeg for all local media processing, and stores all assets on Amazon S3.

This is a **worker API** — it does not contain any LLM logic. The LLM orchestration (scene planning, narration writing, prompt generation) is handled upstream by n8n. This API receives structured payloads and returns finished videos.

---

## Core Concept

**Two rendering channels exist to control cost:**

1. **`kenburns` channel (cheap/fast):** Generate image → apply Ken Burns pan/zoom/drift effects via FFmpeg → overlay voiceover. No animation API calls. Near-zero cost after image generation.

2. **`animated` channel (premium):** Generate image → send to Kie.ai image-to-video animation API → get animated clip → overlay voiceover. Consumes animation credits per scene.

Both channels share the same assembly pipeline (voiceover generation, scene concatenation, background music mixing, subtitle burning, final export).

A typical video is ~7 minutes long, with ~5 seconds per scene, resulting in ~84 scenes per project.

---

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI (async)
- **Task Queue:** Celery with Redis as broker and result backend
- **Database:** PostgreSQL (project state, scene tracking, job history)
- **Media Processing:** FFmpeg (installed on server, called via subprocess)
- **Storage:** Amazon S3 (all media assets — intermediate and final)
- **Reverse Proxy:** Nginx (in production)
- **Containerization:** Docker + Docker Compose for the full stack

---

## Project Structure

```
media-master-api/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── alembic/                          # DB migrations
│   ├── alembic.ini
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                       # FastAPI app entry point
│   ├── config.py                     # Settings from env vars (pydantic-settings)
│   ├── database.py                   # SQLAlchemy async engine + session
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── router.py             # Main v1 router
│   │   │   ├── render.py             # POST /render, GET /render/{id}, POST /render/{id}/retry
│   │   │   ├── projects.py           # CRUD for projects
│   │   │   ├── health.py             # Health check endpoint
│   │   │   └── webhooks.py           # Webhook management
│   │   └── deps.py                   # Shared dependencies (DB session, auth)
│   │
│   ├── models/                       # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── project.py                # Project model
│   │   ├── render_job.py             # RenderJob model
│   │   └── scene.py                  # Scene model (per-scene state tracking)
│   │
│   ├── schemas/                      # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── render.py                 # RenderRequest, RenderResponse, ScenePayload
│   │   └── project.py                # Project schemas
│   │
│   ├── services/                     # External API integrations
│   │   ├── __init__.py
│   │   ├── kie_ai.py                 # Kie.ai client (image gen + animation)
│   │   ├── elevenlabs.py             # ElevenLabs TTS client
│   │   ├── s3.py                     # S3 upload/download/presigned URLs
│   │   └── webhook.py                # Webhook dispatcher (notify n8n on completion)
│   │
│   ├── pipeline/                     # Core rendering pipeline
│   │   ├── __init__.py
│   │   ├── orchestrator.py           # Main pipeline coordinator
│   │   ├── image_generator.py        # Scene image generation step
│   │   ├── voice_generator.py        # Scene voiceover generation step
│   │   ├── animator.py               # Kie.ai animation step (animated channel)
│   │   ├── kenburns.py               # Ken Burns effect generator (kenburns channel)
│   │   ├── scene_assembler.py        # Per-scene: sync video + audio + subtitles
│   │   └── video_assembler.py        # Final: concatenate all scenes, add music, export
│   │
│   ├── workers/                      # Celery task definitions
│   │   ├── __init__.py
│   │   ├── celery_app.py             # Celery app configuration
│   │   ├── render_tasks.py           # Main render task + scene processing tasks
│   │   └── callbacks.py              # Task success/failure callbacks
│   │
│   ├── ffmpeg/                       # FFmpeg command builders
│   │   ├── __init__.py
│   │   ├── commands.py               # Core FFmpeg command construction
│   │   ├── kenburns_effects.py       # Ken Burns effect presets and filter graphs
│   │   ├── transitions.py            # Scene transition effects
│   │   ├── subtitles.py              # Subtitle burning (ASS/SRT generation)
│   │   ├── audio.py                  # Audio mixing, normalization, ducking
│   │   └── concat.py                 # Video concatenation strategies
│   │
│   └── utils/
│       ├── __init__.py
│       ├── retry.py                  # Exponential backoff retry decorator
│       ├── timing.py                 # Duration calculation, speed adjustment
│       └── cleanup.py                # Temp file cleanup
│
├── tests/
│   ├── test_pipeline/
│   ├── test_services/
│   ├── test_ffmpeg/
│   └── conftest.py
│
└── scripts/
    ├── setup_db.sh
    └── seed_test_data.py
```

---

## Database Schema

### projects table
```sql
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### render_jobs table
```sql
CREATE TABLE render_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('kenburns', 'animated')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'assembling', 'completed', 'failed', 'partial_failure')),
    total_scenes INTEGER NOT NULL,
    completed_scenes INTEGER DEFAULT 0,
    failed_scenes INTEGER DEFAULT 0,
    settings JSONB NOT NULL,                    -- resolution, bg music, subtitle style, etc.
    webhook_url VARCHAR(500),                   -- n8n webhook to call on completion
    final_video_url VARCHAR(500),               -- S3 URL of finished video
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### scenes table
```sql
CREATE TABLE scenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    render_job_id UUID REFERENCES render_jobs(id) ON DELETE CASCADE,
    scene_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'generating_image', 'generating_voice', 'animating',
                          'applying_effects', 'assembling', 'completed', 'failed')),
    -- Input data (from n8n)
    image_prompt TEXT NOT NULL,
    animation_prompt TEXT,                       -- NULL for kenburns channel
    narration_text TEXT NOT NULL,
    voice_id VARCHAR(100) NOT NULL,
    -- Output artifacts (S3 URLs)
    image_url VARCHAR(500),
    voice_url VARCHAR(500),
    raw_video_url VARCHAR(500),                  -- animated clip or kenburns clip
    assembled_scene_url VARCHAR(500),            -- final scene with audio + subtitles
    -- Metadata
    voice_duration_seconds FLOAT,                -- actual TTS audio length (drives timing)
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(render_job_id, scene_number)
);
```

---

## API Endpoints

### POST /api/v1/render
Start a new render job. This is the main endpoint n8n calls.

**Request body:**
```json
{
    "project_name": "AI Revolution Episode 12",
    "channel": "kenburns",
    "webhook_url": "https://your-n8n-instance.com/webhook/render-complete",
    "settings": {
        "resolution": "1080x1920",
        "fps": 30,
        "background_music": "ambient_tech",
        "background_music_volume": 0.15,
        "subtitle_enabled": true,
        "subtitle_style": "bold_center",
        "transition_type": "crossfade",
        "transition_duration_ms": 500
    },
    "scenes": [
        {
            "scene_number": 1,
            "image_prompt": "A futuristic cityscape at sunset, towering glass buildings reflecting orange light, cinematic wide angle, 8k quality",
            "animation_prompt": "Slow camera pan from left to right revealing the city skyline, gentle clouds moving",
            "narration_text": "In the year 2045, the world had changed in ways no one could have predicted.",
            "voice_id": "pNInz6obpgDQGcFmaJgB"
        },
        {
            "scene_number": 2,
            "image_prompt": "...",
            "animation_prompt": "...",
            "narration_text": "...",
            "voice_id": "pNInz6obpgDQGcFmaJgB"
        }
    ]
}
```

**Response:**
```json
{
    "job_id": "uuid-here",
    "status": "pending",
    "total_scenes": 84,
    "monitor_url": "/api/v1/render/uuid-here/status",
    "message": "Render job queued successfully"
}
```

### GET /api/v1/render/{job_id}/status
Poll for job status. Designed for n8n's HTTP polling node.

**Response:**
```json
{
    "job_id": "uuid-here",
    "status": "processing",
    "channel": "kenburns",
    "progress": {
        "total_scenes": 84,
        "completed_scenes": 47,
        "failed_scenes": 1,
        "percentage": 55.95
    },
    "final_video_url": null,
    "estimated_completion_minutes": 12,
    "scenes": [
        {
            "scene_number": 1,
            "status": "completed",
            "assembled_scene_url": "https://s3.../scene_001.mp4"
        },
        {
            "scene_number": 48,
            "status": "generating_image",
            "assembled_scene_url": null
        }
    ]
}
```

### POST /api/v1/render/{job_id}/retry
Retry failed scenes within a job without restarting from scratch.

**Request body:**
```json
{
    "scene_numbers": [14, 37],
    "retry_all_failed": false
}
```

### POST /api/v1/render/{job_id}/cancel
Cancel a running render job. Stops all pending scene processing.

### GET /api/v1/health
Health check. Returns service status, FFmpeg version, Redis/DB connectivity, and S3 access.

---

## Pipeline Logic (orchestrator.py)

This is the core brain. When a render job is received:

```
1. Create render_job and scene records in DB (status: pending)
2. Upload job to Celery task queue
3. Celery task picks up the job:
   a. Group scenes into batches of N (configurable, default 10)
   b. For each batch, process scenes CONCURRENTLY:
      - For EACH scene (parallel within batch):
        i.   Generate image via Kie.ai → upload to S3 → save URL
        ii.  Generate voiceover via ElevenLabs → upload to S3 → save URL + duration
             (steps i and ii run in parallel for each scene)
        iii. WAIT for both image and voice to complete
        iv.  IF channel == "animated":
                Send image to Kie.ai animation API with animation_prompt → upload to S3
             ELIF channel == "kenburns":
                Apply Ken Burns effect via FFmpeg (duration = voice_duration) → upload to S3
        v.   Assemble scene: sync video to voice duration + burn subtitles → upload to S3
        vi.  Update scene status to "completed"
   c. After ALL batches complete:
      - Concatenate all completed scenes in order
      - Mix in background music (duck under voice, normalize)
      - Apply transitions between scenes
      - Export final video → upload to S3
      - Update render_job status to "completed" with final_video_url
      - Fire webhook to n8n with the result
```

### Concurrency & Rate Limiting

- Use `asyncio.Semaphore` to limit concurrent API calls per service:
  - `KIE_AI_CONCURRENCY = 5` (configurable)
  - `ELEVENLABS_CONCURRENCY = 5` (configurable)
- Use `BATCH_SIZE = 10` to control how many scenes process at once
- Implement exponential backoff retry (3 attempts) on all API calls
- Track API credits/costs per render job (optional, for monitoring)

### Error Handling Strategy

- **Scene-level failure isolation:** If scene 47 fails after 3 retries, mark it as `failed` and continue with remaining scenes.
- **Partial completion:** If >90% of scenes succeed, assemble what we have and mark the job as `partial_failure` with a list of missing scene numbers. The final video will have a black frame placeholder or skip for failed scenes.
- **Full failure:** If <50% of scenes succeed, mark the entire job as `failed`.
- **Retryable errors:** API rate limits (429), timeouts, and 5xx errors trigger automatic retry with exponential backoff.
- **Non-retryable errors:** 400/401/403 errors fail immediately (bad prompt, auth issue).

---

## FFmpeg Command Details

### Ken Burns Effects (kenburns_effects.py)

Generate a variety of pan/zoom effects to keep the visual interesting across 84 scenes. Randomly assign or cycle through effects per scene.

**Available effect presets:**
```python
KENBURNS_PRESETS = {
    "zoom_in_center": "zoompan=z='min(zoom+0.0015,1.5)':d={duration}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}",
    "zoom_out_center": "zoompan=z='if(eq(on,1),1.5,max(zoom-0.0015,1.0))':d={duration}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}",
    "pan_left_to_right": "zoompan=z='1.3':d={duration}:x='if(eq(on,1),0,min(x+2,(iw-iw/zoom)))':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}",
    "pan_right_to_left": "zoompan=z='1.3':d={duration}:x='if(eq(on,1),(iw-iw/zoom),max(x-2,0))':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}",
    "pan_top_to_bottom": "zoompan=z='1.3':d={duration}:x='iw/2-(iw/zoom/2)':y='if(eq(on,1),0,min(y+2,(ih-ih/zoom)))':s={resolution}:fps={fps}",
    "pan_bottom_to_top": "zoompan=z='1.3':d={duration}:x='iw/2-(iw/zoom/2)':y='if(eq(on,1),(ih-ih/zoom),max(y-2,0))':s={resolution}:fps={fps}",
    "zoom_in_top_left": "zoompan=z='min(zoom+0.0015,1.5)':d={duration}:x='0':y='0':s={resolution}:fps={fps}",
    "zoom_in_bottom_right": "zoompan=z='min(zoom+0.0015,1.5)':d={duration}:x='iw-(iw/zoom)':y='ih-(ih/zoom)':s={resolution}:fps={fps}",
    "slow_drift": "zoompan=z='1.1':d={duration}:x='iw/2-(iw/zoom/2)+sin(on/50)*50':y='ih/2-(ih/zoom/2)+cos(on/50)*30':s={resolution}:fps={fps}",
}
```

**Ken Burns scene generation command:**
```bash
ffmpeg -loop 1 -i scene_image.png \
    -vf "zoompan=z='min(zoom+0.0015,1.5)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30" \
    -t {voice_duration} \
    -c:v libx264 -pix_fmt yuv420p \
    scene_001_video.mp4
```

### Scene Assembly (per scene)
```bash
# Combine video clip with voiceover audio, match durations
ffmpeg -i scene_video.mp4 -i scene_voice.mp3 \
    -filter_complex "[0:v]setpts=PTS*{speed_factor}[v];[1:a]anull[a]" \
    -map "[v]" -map "[a]" \
    -c:v libx264 -c:a aac -shortest \
    scene_001_assembled.mp4
```

### Duration Synchronization Logic
```python
def calculate_speed_factor(video_duration: float, voice_duration: float) -> float:
    """
    Adjust video speed to match voice duration.
    - If video is shorter than voice: slow down video (or loop)
    - If video is longer than voice: speed up video (or trim)
    """
    if video_duration <= 0:
        raise ValueError("Invalid video duration")

    ratio = video_duration / voice_duration

    # If video is way too short (less than half the voice), loop it
    if ratio < 0.5:
        return None  # Signal to use loop strategy instead

    # Otherwise adjust speed
    return ratio


def loop_video_to_duration(video_path: str, target_duration: float, output_path: str):
    """Loop a short video clip to match target duration."""
    cmd = [
        "ffmpeg", "-stream_loop", "-1",
        "-i", video_path,
        "-t", str(target_duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        output_path
    ]
    subprocess.run(cmd, check=True)
```

### Subtitle Burning
```python
def generate_ass_subtitle(narration_text: str, duration: float, style: str) -> str:
    """Generate ASS subtitle file for a scene."""
    # Style presets
    styles = {
        "bold_center": r"Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1",
        "bottom_bar": r"Style: Default,Arial,18,&H00FFFFFF,&H000000FF,&H00000000,&HC0000000,-1,0,0,0,100,100,0,0,1,3,0,2,10,10,50,1",
        "minimal": r"Style: Default,Arial,16,&H00FFFFFF,&H000000FF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,20,1",
    }
    # Word-by-word timing or sentence-level timing based on narration length
    ...
```

### Final Video Assembly
```bash
# 1. Create concat file
echo "file 'scene_001.mp4'" > concat_list.txt
echo "file 'scene_002.mp4'" >> concat_list.txt
...

# 2. Concatenate with crossfade transitions
ffmpeg -f concat -safe 0 -i concat_list.txt \
    -c:v libx264 -c:a aac \
    output_no_music.mp4

# 3. Mix background music (ducked under voice)
ffmpeg -i output_no_music.mp4 -i background_music.mp3 \
    -filter_complex "[1:a]volume=0.15,aloop=loop=-1:size=2e+09[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[aout]" \
    -map 0:v -map "[aout]" \
    -c:v copy -c:a aac \
    final_output.mp4

# 4. Normalize audio
ffmpeg -i final_output.mp4 \
    -af loudnorm=I=-16:TP=-1.5:LRA=11 \
    -c:v copy \
    final_normalized.mp4
```

---

## External Service Integration

### Kie.ai Client (services/kie_ai.py)

**IMPORTANT:** Before implementing, read the Kie.ai API documentation at https://kie.ai/ to get the exact endpoint URLs, authentication method, request/response formats, and available model parameters. The client should be structured as follows but adapted to match their actual API:

```python
class KieAIClient:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.session = httpx.AsyncClient(timeout=120.0)

    async def generate_image(self, prompt: str, resolution: str = "1080x1920",
                              style: str = None, reference_image_url: str = None) -> bytes:
        """
        Generate image from text prompt.
        Returns image bytes.
        Handle polling if Kie.ai uses async task pattern (submit → poll → download).
        """
        ...

    async def animate_image(self, image_url: str, animation_prompt: str,
                             duration_seconds: float = 5.0) -> bytes:
        """
        Convert static image to animated video.
        Returns video bytes.
        This is likely an async/polling endpoint — submit task, poll for completion, download result.
        """
        ...

    async def poll_task(self, task_id: str, max_wait: int = 300, interval: int = 5) -> dict:
        """Generic task polling for async Kie.ai operations."""
        ...
```

### ElevenLabs Client (services/elevenlabs.py)

```python
class ElevenLabsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.elevenlabs.io/v1"
        self.session = httpx.AsyncClient(timeout=60.0)

    async def generate_speech(self, text: str, voice_id: str,
                               model_id: str = "eleven_multilingual_v2",
                               stability: float = 0.5,
                               similarity_boost: float = 0.75) -> tuple[bytes, float]:
        """
        Generate speech audio from text.
        Returns (audio_bytes, duration_seconds).
        """
        response = await self.session.post(
            f"{self.base_url}/text-to-speech/{voice_id}",
            headers={"xi-api-key": self.api_key},
            json={
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity_boost
                }
            }
        )
        audio_bytes = response.content
        # Calculate duration from audio
        duration = self._get_audio_duration(audio_bytes)
        return audio_bytes, duration
```

### S3 Client (services/s3.py)

```python
class S3Storage:
    def __init__(self, bucket: str, region: str, access_key: str, secret_key: str):
        self.client = boto3.client('s3', region_name=region,
                                    aws_access_key_id=access_key,
                                    aws_secret_access_key=secret_key)
        self.bucket = bucket

    def upload_file(self, file_bytes: bytes, key: str, content_type: str) -> str:
        """Upload file and return the S3 URL."""
        self.client.put_object(Bucket=self.bucket, Key=key, Body=file_bytes,
                                ContentType=content_type)
        return f"https://{self.bucket}.s3.amazonaws.com/{key}"

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned download URL."""
        ...

    def download_file(self, key: str) -> bytes:
        """Download file from S3."""
        ...
```

**S3 Key Structure:**
```
media-master/
├── {project_id}/
│   ├── {job_id}/
│   │   ├── images/
│   │   │   ├── scene_001.png
│   │   │   ├── scene_002.png
│   │   │   └── ...
│   │   ├── voices/
│   │   │   ├── scene_001.mp3
│   │   │   ├── scene_002.mp3
│   │   │   └── ...
│   │   ├── animations/
│   │   │   ├── scene_001.mp4
│   │   │   └── ...
│   │   ├── scenes/
│   │   │   ├── scene_001_assembled.mp4
│   │   │   ├── scene_002_assembled.mp4
│   │   │   └── ...
│   │   └── final/
│   │       └── final_output.mp4
```

---

## Configuration (.env)

```env
# App
APP_NAME=media-master-api
APP_ENV=production
APP_PORT=8000
API_KEY=your-api-secret-key-here

# Database
DATABASE_URL=postgresql+asyncpg://media:password@localhost:5432/media_master

# Redis
REDIS_URL=redis://localhost:6379/0

# Kie.ai
KIE_AI_API_KEY=your-kie-ai-key
KIE_AI_BASE_URL=https://api.kie.ai/v1
KIE_AI_CONCURRENCY=5

# ElevenLabs
ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_CONCURRENCY=5

# AWS S3
S3_BUCKET=your-media-bucket
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# Pipeline
BATCH_SIZE=10
MAX_RETRIES=3
SCENE_FAILURE_THRESHOLD=0.5
TEMP_DIR=/tmp/media-master

# FFmpeg
FFMPEG_PATH=/usr/bin/ffmpeg
FFPROBE_PATH=/usr/bin/ffprobe
```

---

## Docker Compose

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
      - redis
    volumes:
      - temp_media:/tmp/media-master
    deploy:
      resources:
        limits:
          memory: 4G

  celery_worker:
    build: .
    command: celery -A app.workers.celery_app worker -l info -c 4 --max-tasks-per-child=50
    env_file: .env
    depends_on:
      - db
      - redis
    volumes:
      - temp_media:/tmp/media-master
    deploy:
      resources:
        limits:
          memory: 8G

  celery_beat:
    build: .
    command: celery -A app.workers.celery_app beat -l info
    env_file: .env
    depends_on:
      - redis

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: media_master
      POSTGRES_USER: media
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data

volumes:
  pgdata:
  redisdata:
  temp_media:
```

---

## Dockerfile

```dockerfile
FROM python:3.11-slim

# Install FFmpeg and system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

---

## Requirements

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
celery[redis]==5.4.0
redis==5.0.0
sqlalchemy[asyncio]==2.0.35
asyncpg==0.30.0
alembic==1.13.0
pydantic==2.9.0
pydantic-settings==2.5.0
httpx==0.27.0
boto3==1.35.0
python-multipart==0.0.9
mutagen==1.47.0
Pillow==10.4.0
aiofiles==24.1.0
tenacity==9.0.0
```

---

## Webhook Notification (to n8n)

When a render job completes (or fails), send a POST to the webhook URL provided in the original request:

```json
{
    "event": "render.completed",
    "job_id": "uuid-here",
    "project_name": "AI Revolution Episode 12",
    "status": "completed",
    "channel": "kenburns",
    "final_video_url": "https://s3.amazonaws.com/bucket/media-master/.../final_output.mp4",
    "duration_seconds": 420,
    "total_scenes": 84,
    "completed_scenes": 84,
    "failed_scenes": 0,
    "processing_time_seconds": 847,
    "timestamp": "2025-01-15T14:30:00Z"
}
```

For failures:
```json
{
    "event": "render.failed",
    "job_id": "uuid-here",
    "status": "failed",
    "error_message": "Too many scenes failed (42/84). Below 50% threshold.",
    "completed_scenes": 42,
    "failed_scenes": 42,
    "failed_scene_numbers": [3, 7, 12, ...],
    "retry_url": "/api/v1/render/uuid-here/retry"
}
```

---

## Authentication

Simple API key authentication via header. This API is only called by n8n, not public-facing.

```python
# deps.py
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

All endpoints except `/health` require the `X-API-Key` header.

---

## Key Implementation Notes

1. **Voice duration drives everything.** The voiceover audio length determines how long each scene's video needs to be. Generate voice first (or in parallel with image), then use its duration to set the Ken Burns effect duration or to time-stretch the animated clip.

2. **Temp file management is critical.** With 84 scenes, you'll have hundreds of intermediate files. Use a structured temp directory per job (`/tmp/media-master/{job_id}/`) and clean it up after successful S3 upload of the final video.

3. **FFmpeg subprocess calls should be async.** Use `asyncio.create_subprocess_exec` to avoid blocking the event loop during video processing.

4. **Ken Burns effect variety.** Don't apply the same effect to every scene. Cycle through the presets or randomly assign them to keep the video visually interesting. Avoid two adjacent scenes having the same effect.

5. **Kie.ai API is likely async/polling.** Most image and video generation APIs use a submit-then-poll pattern. The client must handle: submit task → get task_id → poll every N seconds → download result when done. Build this polling logic into the client with configurable timeout.

6. **Background music looping.** The background music track will likely be shorter than 7 minutes. Use FFmpeg's `-stream_loop -1` to loop it, and `-af volume=0.15` to keep it subtle under the narration.

7. **Subtitle timing.** For word-by-word or sentence-level subtitles, estimate timing from the narration text length proportionally against the voice duration. More advanced: use ElevenLabs word-level timestamps if available in their API response.

8. **Memory management on Contabo.** Processing 84 scenes with video files can eat RAM. Process in batches, upload each scene to S3 immediately after assembly, and delete local temp files aggressively. Don't hold all 84 video files in memory/disk simultaneously.

9. **Idempotency.** If n8n accidentally sends the same render request twice, the API should detect the duplicate (by project_name + scene hash) and return the existing job instead of creating a new one. Or just let it create a new job — simpler and n8n can handle dedup on its side.

10. **Logging.** Use structured logging (structlog or python-json-logger) with job_id and scene_number in every log line. Essential for debugging failed scenes in a 84-scene pipeline.

---

## Build Order (Suggested Implementation Sequence)

1. **Phase 1 — Skeleton:** FastAPI app, config, database models, migrations, Docker Compose, health endpoint
2. **Phase 2 — Services:** S3 client, ElevenLabs client, Kie.ai client (with mocks for testing)
3. **Phase 3 — FFmpeg:** Ken Burns effect generator, scene assembly, video concatenation, subtitle burning
4. **Phase 4 — Pipeline:** Scene processor, orchestrator, duration sync logic
5. **Phase 5 — Celery:** Task definitions, batch processing, error handling, retry logic
6. **Phase 6 — API:** Render endpoint, status polling, retry endpoint, webhook notifications
7. **Phase 7 — Polish:** Logging, monitoring, cleanup tasks, edge case handling
