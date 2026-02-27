import structlog
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import verify_api_key, get_session
from app.models.project import Project
from app.models.render_job import RenderJob
from app.models.scene import Scene
from app.schemas.render import (
    RenderRequest,
    RenderResponse,
    RenderStatusResponse,
    RenderProgress,
    SceneStatusItem,
    RetryRequest,
)

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.post("", response_model=RenderResponse, status_code=202)
async def start_render(
    payload: RenderRequest,
    db: AsyncSession = Depends(get_session),
):
    # Get or create project
    result = await db.execute(
        select(Project).where(Project.name == payload.project_name)
    )
    project = result.scalar_one_or_none()
    if not project:
        project = Project(name=payload.project_name)
        db.add(project)
        await db.flush()

    # Create render job
    job = RenderJob(
        project_id=project.id,
        channel=payload.channel,
        status="pending",
        total_scenes=len(payload.scenes),
        settings=payload.settings.model_dump(),
        webhook_url=payload.webhook_url,
    )
    db.add(job)
    await db.flush()

    # Create scene records
    for scene_payload in payload.scenes:
        scene = Scene(
            render_job_id=job.id,
            scene_number=scene_payload.scene_number,
            image_prompt=scene_payload.image_prompt,
            animation_prompt=scene_payload.animation_prompt,
            narration_text=scene_payload.narration_text,
            voice_id=scene_payload.voice_id,
        )
        db.add(scene)

    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    from app.workers.render_tasks import process_render_job
    process_render_job.delay(str(job.id))

    logger.info("Render job queued", job_id=str(job.id), total_scenes=job.total_scenes)

    return RenderResponse(
        job_id=job.id,
        status=job.status,
        total_scenes=job.total_scenes,
        monitor_url=f"/api/v1/render/{job.id}/status",
        message="Render job queued successfully",
    )


@router.get("/{job_id}/status", response_model=RenderStatusResponse)
async def get_render_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(RenderJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")

    result = await db.execute(
        select(Scene)
        .where(Scene.render_job_id == job_id)
        .order_by(Scene.scene_number)
    )
    scenes = result.scalars().all()

    percentage = 0.0
    if job.total_scenes > 0:
        percentage = round((job.completed_scenes / job.total_scenes) * 100, 2)

    # Rough estimate: ~10s per scene for kenburns, ~60s for animated
    est_minutes = None
    if job.status == "processing" and job.total_scenes > 0:
        remaining = job.total_scenes - job.completed_scenes - job.failed_scenes
        seconds_per_scene = 10 if job.channel == "kenburns" else 60
        est_minutes = round((remaining * seconds_per_scene) / 60, 1)

    return RenderStatusResponse(
        job_id=job.id,
        status=job.status,
        channel=job.channel,
        progress=RenderProgress(
            total_scenes=job.total_scenes,
            completed_scenes=job.completed_scenes,
            failed_scenes=job.failed_scenes,
            percentage=percentage,
        ),
        final_video_url=job.final_video_url,
        estimated_completion_minutes=est_minutes,
        scenes=[
            SceneStatusItem(
                scene_number=s.scene_number,
                status=s.status,
                assembled_scene_url=s.assembled_scene_url,
            )
            for s in scenes
        ],
    )


@router.post("/{job_id}/retry", status_code=202)
async def retry_render(
    job_id: UUID,
    payload: RetryRequest,
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(RenderJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    if job.status not in ("failed", "partial_failure", "completed"):
        raise HTTPException(
            status_code=400,
            detail="Can only retry jobs in failed, partial_failure, or completed state",
        )

    # Determine which scenes to retry
    query = select(Scene).where(Scene.render_job_id == job_id)
    if payload.retry_all_failed:
        query = query.where(Scene.status == "failed")
    elif payload.scene_numbers:
        query = query.where(Scene.scene_number.in_(payload.scene_numbers))
    else:
        raise HTTPException(status_code=400, detail="Specify scene_numbers or retry_all_failed=true")

    result = await db.execute(query)
    scenes = result.scalars().all()

    if not scenes:
        raise HTTPException(status_code=404, detail="No matching scenes found to retry")

    # Reset scene statuses
    for scene in scenes:
        scene.status = "pending"
        scene.error_message = None
        scene.retry_count += 1

    job.status = "processing"
    job.failed_scenes = max(0, job.failed_scenes - len(scenes))
    await db.commit()

    from app.workers.render_tasks import retry_scenes
    retry_scenes.delay(str(job_id), [s.scene_number for s in scenes])

    return {
        "job_id": str(job_id),
        "retrying_scenes": [s.scene_number for s in scenes],
        "message": f"Retrying {len(scenes)} scene(s)",
    }


@router.post("/{job_id}/cancel", status_code=200)
async def cancel_render(
    job_id: UUID,
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(RenderJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found")
    if job.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="Job already finished")

    job.status = "failed"
    job.error_message = "Cancelled by user"
    job.completed_at = datetime.now(timezone.utc)

    # Mark pending scenes as failed
    result = await db.execute(
        select(Scene).where(
            Scene.render_job_id == job_id,
            Scene.status == "pending",
        )
    )
    for scene in result.scalars().all():
        scene.status = "failed"
        scene.error_message = "Job cancelled"

    await db.commit()

    # Revoke celery tasks
    from app.workers.celery_app import celery_app
    celery_app.control.revoke(str(job_id), terminate=True)

    logger.info("Render job cancelled", job_id=str(job_id))
    return {"job_id": str(job_id), "status": "cancelled"}
