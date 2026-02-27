import os
import structlog
from app.ffmpeg.commands import run_ffmpeg
from app.ffmpeg.kenburns_effects import build_kenburns_filter
from app.services.s3 import s3, get_s3_key
from app.utils.cleanup import safe_delete
from app.config import settings

logger = structlog.get_logger()


async def apply_kenburns_and_upload(
    project_id: str,
    job_id: str,
    scene_number: int,
    image_local_path: str,
    voice_duration: float,
    resolution: str,
    fps: int,
    keypoints: list[dict] | None = None,
    pan_direction: str | None = None,
    temp_dir: str | None = None,
) -> tuple[str, str]:
    """
    Apply Ken Burns effect to a static image and upload to S3.
    Returns (s3_url, effect_name).
    """
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info("Applying Ken Burns effect", effect="keypoints" if keypoints else pan_direction or "auto")

    effect_name, filter_str = build_kenburns_filter(
        scene_number=scene_number,
        voice_duration=voice_duration,
        resolution=resolution,
        fps=fps,
        keypoints=keypoints,
        pan_direction=pan_direction,
    )

    out_dir = temp_dir or os.path.join(settings.temp_dir, job_id, "videos")
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, f"scene_{scene_number:04d}_kenburns.mp4")

    await run_ffmpeg(
        "-loop", "1",
        "-i", image_local_path,
        "-vf", filter_str,
        "-t", str(voice_duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        output_path,
        timeout=120,
    )

    key = get_s3_key(project_id, job_id, "animations", f"scene_{scene_number:04d}.mp4")
    url = s3.upload_file(output_path, key, "video/mp4")
    safe_delete(output_path)

    log.info("Ken Burns clip uploaded", url=url, effect=effect_name)
    return url, effect_name
