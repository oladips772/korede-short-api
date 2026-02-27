import asyncio
import os
import structlog
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.render_job import RenderJob
from app.models.scene import Scene
from app.pipeline.image_generator import generate_and_upload_image
from app.pipeline.voice_generator import generate_and_upload_voice
from app.pipeline.animator import animate_and_upload
from app.pipeline.kenburns import apply_kenburns_and_upload
from app.pipeline.scene_assembler import assemble_scene
from app.pipeline.video_assembler import assemble_final_video
from app.services.s3 import s3
from app.services.webhook import dispatch_webhook, build_completion_payload, build_failure_payload
from app.utils.cleanup import ensure_job_dirs, cleanup_job_temp_dir, safe_delete
from app.ffmpeg.commands import get_video_duration
from app.database import AsyncSessionLocal
from app.config import settings

logger = structlog.get_logger()

# Map Kie.ai resolution codes + aspect ratio → FFmpeg pixel dimensions (WxH)
_RESOLUTION_MAP: dict[tuple[str, str], str] = {
    ("1K", "16:9"): "1280x720",
    ("1K", "9:16"): "720x1280",
    ("1K", "1:1"): "1024x1024",
    ("1K", "4:3"): "1024x768",
    ("2K", "16:9"): "1920x1080",
    ("2K", "9:16"): "1080x1920",
    ("2K", "1:1"): "2048x2048",
    ("2K", "4:3"): "2048x1536",
    ("4K", "16:9"): "3840x2160",
    ("4K", "9:16"): "2160x3840",
    ("4K", "1:1"): "4096x4096",
    ("4K", "4:3"): "4096x3072",
}


def _ffmpeg_resolution(resolution: str, aspect_ratio: str) -> str:
    """Convert a Kie.ai resolution code (e.g. '1K') to FFmpeg pixel dimensions (e.g. '1280x720').
    Falls back to the raw value if it already looks like a pixel dimension."""
    if "x" in resolution:
        return resolution
    return _RESOLUTION_MAP.get((resolution.upper(), aspect_ratio), "1280x720")


async def run_render_pipeline(job_id: str, db: AsyncSession) -> None:
    """Main pipeline entry point. Runs the full render for a job."""
    log = logger.bind(job_id=job_id)

    job = await db.get(RenderJob, job_id)
    if not job:
        log.error("Render job not found")
        return

    job.status = "processing"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()

    result = await db.execute(
        select(Scene)
        .where(Scene.render_job_id == job.id)
        .order_by(Scene.scene_number)
    )
    scenes = result.scalars().all()

    project_id = str(job.project_id)
    job_settings = job.settings
    batch_size = settings.batch_size
    temp_dirs = ensure_job_dirs(job_id)

    log.info("Starting pipeline", total_scenes=len(scenes), channel=job.channel)

    assembled_urls: dict[int, str] = {}

    for batch_start in range(0, len(scenes), batch_size):
        batch = scenes[batch_start : batch_start + batch_size]
        log.info("Processing batch", batch_start=batch_start, batch_size=len(batch))

        tasks = [
            process_scene(
                scene_id=str(s.id),
                job_id=job_id,
                project_id=project_id,
                job_settings=job_settings,
                temp_dirs=temp_dirs,
            )
            for s in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for scene, result in zip(batch, results):
            if isinstance(result, Exception):
                log.error("Scene failed", scene_number=scene.scene_number, error=str(result))
                scene.status = "failed"
                scene.error_message = str(result)
                job.failed_scenes += 1
            else:
                assembled_urls[scene.scene_number] = result
                job.completed_scenes += 1

        await db.commit()

    total = job.total_scenes
    completed = job.completed_scenes
    failed = job.failed_scenes
    success_ratio = completed / total if total > 0 else 0

    if success_ratio < settings.scene_failure_threshold:
        job.status = "failed"
        job.error_message = (
            f"Too many scenes failed ({failed}/{total}). "
            f"Below {settings.scene_failure_threshold * 100:.0f}% threshold."
        )
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()
        if job.webhook_url:
            failed_nums = [s.scene_number for s in scenes if s.status == "failed"]
            await dispatch_webhook(job.webhook_url, build_failure_payload(job, failed_nums))
        cleanup_job_temp_dir(job_id)
        return

    job.status = "assembling"
    await db.commit()

    ordered_urls = [
        assembled_urls[scene.scene_number]
        for scene in scenes
        if scene.scene_number in assembled_urls
    ]

    try:
        final_url = await assemble_final_video(
            project_id=project_id,
            job_id=job_id,
            assembled_scene_urls=ordered_urls,
            job_settings=job_settings,
            temp_base=temp_dirs["final"],
        )

        job.final_video_url = final_url
        job.status = "completed" if failed == 0 else "partial_failure"
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()

        project = await db.get(job.__class__, job.project_id)
        project_name = getattr(project, "name", "") if project else ""

        if job.webhook_url:
            failed_nums = [s.scene_number for s in scenes if s.status == "failed"]
            await dispatch_webhook(
                job.webhook_url,
                build_completion_payload(job, project_name, failed_nums),
            )

    except Exception as e:
        log.error("Final assembly failed", error=str(e))
        job.status = "failed"
        job.error_message = f"Final assembly failed: {e}"
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()

    finally:
        cleanup_job_temp_dir(job_id)


async def process_scene(
    scene_id: str,
    job_id: str,
    project_id: str,
    job_settings: dict,
    temp_dirs: dict,
) -> str:
    """Process a single scene. Uses its own DB session so scenes can run concurrently."""
    async with AsyncSessionLocal() as db:
        scene = await db.get(Scene, scene_id)
        job = await db.get(RenderJob, job_id)

        log = logger.bind(job_id=job_id, scene_number=scene.scene_number)
        aspect_ratio = job_settings.get("aspect_ratio", "16:9")
        resolution = job_settings.get("resolution", "1K")
        fps = job_settings.get("fps", 30)

        # ── Step 1: Generate image and voice in parallel ────────────────────
        scene.status = "generating_image"
        await db.commit()

        image_task = generate_and_upload_image(
            project_id=project_id,
            job_id=job_id,
            scene_number=scene.scene_number,
            image_prompt=scene.image_prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        )
        voice_task = generate_and_upload_voice(
            project_id=project_id,
            job_id=job_id,
            scene_number=scene.scene_number,
            narration_text=scene.narration_text,
            voice_id=scene.voice_id,
        )

        image_url, (voice_url, voice_duration_estimate) = await asyncio.gather(
            image_task, voice_task
        )

        scene.image_url = image_url
        scene.voice_url = voice_url
        scene.voice_duration_seconds = voice_duration_estimate  # mutagen estimate for reference

        # Download the voice file NOW so we can measure its exact duration with
        # ffprobe before generating the Ken Burns / animation clip.  Using the
        # mutagen estimate risks a mismatch of several hundred milliseconds which
        # causes audio to extend past the video or get cut short.
        voice_key = _url_to_key(voice_url)
        local_voice = os.path.join(
            temp_dirs["voices"], f"scene_{scene.scene_number:04d}.mp3"
        )
        s3.download_file(voice_key, local_voice)
        actual_voice_duration = await get_video_duration(local_voice)

        log.info(
            "Voice durations",
            mutagen_estimate=voice_duration_estimate,
            ffprobe_actual=actual_voice_duration,
        )

        # ── Step 2: Generate video clip ─────────────────────────────────────
        if job.channel == "animated":
            scene.status = "animating"
            await db.commit()

            raw_video_url = await animate_and_upload(
                project_id=project_id,
                job_id=job_id,
                scene_number=scene.scene_number,
                image_url=image_url,
                animation_prompt=scene.animation_prompt or scene.image_prompt,
                voice_duration=actual_voice_duration,
            )
        else:
            # kenburns channel
            scene.status = "applying_effects"
            await db.commit()

            image_key = _url_to_key(image_url)
            local_image = os.path.join(
                temp_dirs["images"], f"scene_{scene.scene_number:04d}.png"
            )
            s3.download_file(image_key, local_image)

            raw_video_url, _ = await apply_kenburns_and_upload(
                project_id=project_id,
                job_id=job_id,
                scene_number=scene.scene_number,
                image_local_path=local_image,
                voice_duration=actual_voice_duration,   # ← exact ffprobe duration
                resolution=_ffmpeg_resolution(resolution, aspect_ratio),
                fps=fps,
                keypoints=scene.ken_burns_keypoints,
                pan_direction=scene.pan_direction,
                temp_dir=temp_dirs["videos"],
            )
            safe_delete(local_image)

        scene.raw_video_url = raw_video_url

        # ── Step 3: Assemble scene (video + audio + subtitles) ───────────────
        scene.status = "assembling"
        await db.commit()

        video_key = _url_to_key(raw_video_url)
        local_video = os.path.join(
            temp_dirs["videos"], f"scene_{scene.scene_number:04d}_raw.mp4"
        )
        s3.download_file(video_key, local_video)
        # local_voice is already downloaded from step 1 — no second download needed

        assembled_url = await assemble_scene(
            project_id=project_id,
            job_id=job_id,
            scene_number=scene.scene_number,
            video_local_path=local_video,
            voice_local_path=local_voice,
            voice_duration=actual_voice_duration,
            narration_text=scene.narration_text,
            subtitle_enabled=job_settings.get("subtitle_enabled", True),
            subtitle_style=job_settings.get("subtitle_style", "bold_center"),
            temp_dir=temp_dirs["scenes"],
        )
        safe_delete(local_video)
        safe_delete(local_voice)

        scene.assembled_scene_url = assembled_url
        scene.status = "completed"
        await db.commit()

        log.info("Scene completed", assembled_url=assembled_url)
        return assembled_url


def _url_to_key(s3_url: str) -> str:
    parts = s3_url.split(".s3.amazonaws.com/", 1)
    if len(parts) == 2:
        return parts[1]
    raise ValueError(f"Cannot parse S3 URL: {s3_url}")
