import structlog
from app.services.kie_ai import kie_ai_client
from app.services.s3 import s3, get_s3_key

logger = structlog.get_logger()


async def generate_and_upload_image(
    project_id: str,
    job_id: str,
    scene_number: int,
    image_prompt: str,
    aspect_ratio: str = "16:9",
    resolution: str = "1K",
) -> str:
    """Generate an image via Kie.ai and upload to S3. Returns the S3 URL."""
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info("Generating image")

    image_bytes = await kie_ai_client.generate_image(
        prompt=image_prompt,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )

    key = get_s3_key(project_id, job_id, "images", f"scene_{scene_number:04d}.png")
    url = s3.upload_bytes(image_bytes, key, "image/png")
    log.info("Image uploaded to S3", url=url)
    return url
