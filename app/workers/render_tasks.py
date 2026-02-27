import asyncio
import structlog
from celery import Task
from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.render_job import RenderJob
from app.models.scene import Scene
from app.pipeline.orchestrator import run_render_pipeline

logger = structlog.get_logger()


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="render.process_job",
    max_retries=0,
    acks_late=True,
)
def process_render_job(self: Task, job_id: str) -> dict:
    """Main Celery task: runs the full render pipeline for a job."""
    logger.info("Celery task started", task_id=self.request.id, job_id=job_id)

    async def _run():
        async with AsyncSessionLocal() as db:
            await run_render_pipeline(job_id=job_id, db=db)

    _run_async(_run())
    return {"job_id": job_id, "status": "done"}


@celery_app.task(
    bind=True,
    name="render.retry_scenes",
    max_retries=0,
    acks_late=True,
)
def retry_scenes(self: Task, job_id: str, scene_numbers: list[int]) -> dict:
    """Retry specific scenes in a job."""
    logger.info("Retrying scenes", job_id=job_id, scene_numbers=scene_numbers)

    async def _run():
        async with AsyncSessionLocal() as db:
            job = await db.get(RenderJob, job_id)
            if not job:
                logger.error("Job not found for retry", job_id=job_id)
                return

            result = await db.execute(
                select(Scene).where(
                    Scene.render_job_id == job_id,
                    Scene.scene_number.in_(scene_numbers),
                )
            )
            scenes = result.scalars().all()

            from app.pipeline.orchestrator import process_scene
            from app.utils.cleanup import ensure_job_dirs
            import asyncio

            project_id = str(job.project_id)
            temp_dirs = ensure_job_dirs(job_id)

            tasks = [
                process_scene(
                    scene_id=str(s.id),
                    job_id=job_id,
                    project_id=project_id,
                    job_settings=job.settings,
                    temp_dirs=temp_dirs,
                )
                for s in scenes
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for scene, res in zip(scenes, results):
                if isinstance(res, Exception):
                    scene.status = "failed"
                    scene.error_message = str(res)
                    job.failed_scenes = min(job.total_scenes, job.failed_scenes + 1)
                else:
                    job.completed_scenes += 1
                    job.failed_scenes = max(0, job.failed_scenes - 1)

            await db.commit()

    _run_async(_run())
    return {"job_id": job_id, "retried_scenes": scene_numbers}
