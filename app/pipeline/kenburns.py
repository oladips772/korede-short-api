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

    voice_duration must be the EXACT duration measured from the actual audio
    file via ffprobe — not the mutagen estimate — so that total_frames and
    the -t trim are perfectly aligned with the narration.
    """
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info(
        "Applying Ken Burns effect",
        effect="keypoints" if keypoints else pan_direction or "auto",
        voice_duration=voice_duration,
        resolution=resolution,
        fps=fps,
    )

    effect_name, zoompan_filter = build_kenburns_filter(
        scene_number=scene_number,
        voice_duration=voice_duration,
        resolution=resolution,
        fps=fps,
        keypoints=keypoints,
        pan_direction=pan_direction,
    )

    # Prepend a high-resolution scale so zoompan has many pixels to work with.
    # This prevents blocky/blurry motion when the source image is small.
    # scale=8000:-2 → width=8000, height computed to keep aspect ratio (even number).
    # zoompan then crops and outputs at the target resolution (s= parameter).
    full_filter = f"scale=8000:-2,{zoompan_filter}"

    out_dir = temp_dir or os.path.join(settings.temp_dir, job_id, "videos")
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, f"scene_{scene_number:04d}_kenburns.mp4")

    await run_ffmpeg(
        "-loop", "1",
        "-i", image_local_path,
        "-vf", full_filter,
        "-t", str(voice_duration),       # safety trim to exact audio length
        "-r", str(fps),                  # explicit output frame rate
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",           # required for concat compatibility
        "-movflags", "+faststart",       # moov atom at start for proper seeking
        output_path,
        timeout=300,                     # scale=8000 is slow; allow extra time
    )

    key = get_s3_key(project_id, job_id, "animations", f"scene_{scene_number:04d}.mp4")
    url = s3.upload_file(output_path, key, "video/mp4")
    safe_delete(output_path)

    log.info("Ken Burns clip uploaded", url=url, effect=effect_name)
    return url, effect_name
