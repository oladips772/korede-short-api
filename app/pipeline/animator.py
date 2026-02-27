import structlog
from app.services.kie_ai import kie_ai_client
from app.services.s3 import s3, get_s3_key

logger = structlog.get_logger()


async def animate_and_upload(
    project_id: str,
    job_id: str,
    scene_number: int,
    image_url: str,
    animation_prompt: str,
    voice_duration: float,
) -> str:
    """Animate image via Kie.ai and upload to S3. Returns the S3 URL of the video clip."""
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info("Animating image via Kie.ai")

    video_bytes = await kie_ai_client.animate_image(
        image_url=image_url,
        animation_prompt=animation_prompt,
        duration_seconds=voice_duration,
    )

    key = get_s3_key(project_id, job_id, "animations", f"scene_{scene_number:04d}.mp4")
    url = s3.upload_bytes(video_bytes, key, "video/mp4")
    log.info("Animation uploaded to S3", url=url)
    return url
