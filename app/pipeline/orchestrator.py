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
from app.database import AsyncSessionLocal
from app.config import settings

logger = structlog.get_logger()


async def run_render_pipeline(job_id: str, db: AsyncSession) -> None:
    """Main pipeline entry point. Runs the full render for a job."""
    log = logger.bind(job_id=job_id)

    job = await db.get(RenderJob, job_id)
    if not job:
        log.error("Render job not found")
        return

    # Update status
    job.status = "processing"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()

    # Load scenes
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

    # Process scenes in batches
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

    # Determine success threshold
    total = job.total_scenes
    completed = job.completed_scenes
    failed = job.failed_scenes
    success_ratio = completed / total if total > 0 else 0

    if success_ratio < settings.scene_failure_threshold:
        job.status = "failed"
        job.error_message = (
            f"Too many scenes failed ({failed}/{total}). Below {settings.scene_failure_threshold * 100:.0f}% threshold."
        )
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()

        if job.webhook_url:
            failed_nums = [s.scene_number for s in scenes if s.status == "failed"]
            await dispatch_webhook(job.webhook_url, build_failure_payload(job, failed_nums))
        cleanup_job_temp_dir(job_id)
        return

    # Assemble final video
    job.status = "assembling"
    await db.commit()

    # Sort assembled scenes by scene number, insert placeholder for failed ones
    ordered_urls = []
    for scene in scenes:
        if scene.scene_number in assembled_urls:
            ordered_urls.append(assembled_urls[scene.scene_number])
        # Failed scenes are skipped (partial_failure)

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

        # Load project name for webhook
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

        # Step 1: Generate image and voice in parallel
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

        image_url, (voice_url, voice_duration) = await asyncio.gather(image_task, voice_task)

        scene.image_url = image_url
        scene.voice_url = voice_url
        scene.voice_duration_seconds = voice_duration

        # Step 2: Generate video clip
        if job.channel == "animated":
            scene.status = "animating"
            await db.commit()

            raw_video_url = await animate_and_upload(
                project_id=project_id,
                job_id=job_id,
                scene_number=scene.scene_number,
                image_url=image_url,
                animation_prompt=scene.animation_prompt or scene.image_prompt,
                voice_duration=voice_duration,
            )
        else:
            # kenburns channel
            scene.status = "applying_effects"
            await db.commit()

            image_key = _url_to_key(image_url)
            local_image = os.path.join(temp_dirs["images"], f"scene_{scene.scene_number:04d}.png")
            s3.download_file(image_key, local_image)

            raw_video_url, _ = await apply_kenburns_and_upload(
                project_id=project_id,
                job_id=job_id,
                scene_number=scene.scene_number,
                image_local_path=local_image,
                voice_duration=voice_duration,
                resolution=resolution,
                fps=fps,
                temp_dir=temp_dirs["videos"],
            )
            safe_delete(local_image)

        scene.raw_video_url = raw_video_url

        # Step 3: Assemble scene (video + audio + subtitles)
        scene.status = "assembling"
        await db.commit()

        video_key = _url_to_key(raw_video_url)
        voice_key = _url_to_key(voice_url)
        local_video = os.path.join(temp_dirs["videos"], f"scene_{scene.scene_number:04d}_raw.mp4")
        local_voice = os.path.join(temp_dirs["voices"], f"scene_{scene.scene_number:04d}.mp3")
        s3.download_file(video_key, local_video)
        s3.download_file(voice_key, local_voice)

        assembled_url = await assemble_scene(
            project_id=project_id,
            job_id=job_id,
            scene_number=scene.scene_number,
            video_local_path=local_video,
            voice_local_path=local_voice,
            voice_duration=voice_duration,
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
