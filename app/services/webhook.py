import structlog
import httpx
from datetime import datetime, timezone

logger = structlog.get_logger()


async def dispatch_webhook(url: str, payload: dict) -> bool:
    """Send a webhook POST. Returns True on success, False on failure."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Webhook dispatched", url=url, status=response.status_code)
            return True
    except Exception as e:
        logger.error("Webhook dispatch failed", url=url, error=str(e))
        return False


def build_completion_payload(job, project_name: str, failed_scene_numbers: list[int]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    processing_time = None
    if job.started_at and job.completed_at:
        processing_time = int((job.completed_at - job.started_at).total_seconds())

    return {
        "event": "render.completed",
        "job_id": str(job.id),
        "project_name": project_name,
        "status": job.status,
        "channel": job.channel,
        "final_video_url": job.final_video_url,
        "total_scenes": job.total_scenes,
        "completed_scenes": job.completed_scenes,
        "failed_scenes": job.failed_scenes,
        "processing_time_seconds": processing_time,
        "timestamp": now,
    }


def build_failure_payload(job, failed_scene_numbers: list[int]) -> dict:
    return {
        "event": "render.failed",
        "job_id": str(job.id),
        "status": "failed",
        "error_message": job.error_message,
        "completed_scenes": job.completed_scenes,
        "failed_scenes": job.failed_scenes,
        "failed_scene_numbers": failed_scene_numbers,
        "retry_url": f"/api/v1/render/{job.id}/retry",
    }
