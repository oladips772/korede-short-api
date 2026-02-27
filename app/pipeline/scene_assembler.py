import os
import structlog
from app.ffmpeg.commands import run_ffmpeg, get_video_duration
from app.ffmpeg.subtitles import generate_ass_subtitle
from app.services.s3 import s3, get_s3_key
from app.utils.timing import calculate_speed_factor
from app.utils.cleanup import safe_delete
from app.config import settings

logger = structlog.get_logger()


async def assemble_scene(
    project_id: str,
    job_id: str,
    scene_number: int,
    video_local_path: str,
    voice_local_path: str,
    voice_duration: float,
    narration_text: str,
    subtitle_enabled: bool,
    subtitle_style: str,
    temp_dir: str | None = None,
) -> str:
    """
    Assemble a single scene: sync video to audio duration, optionally burn subtitles.
    Returns the S3 URL of the assembled scene.
    """
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info("Assembling scene")

    base_dir = temp_dir or os.path.join(settings.temp_dir, job_id, "scenes")
    os.makedirs(base_dir, exist_ok=True)

    video_duration = await get_video_duration(video_local_path)
    speed_factor = calculate_speed_factor(video_duration, voice_duration)

    synced_video = os.path.join(base_dir, f"scene_{scene_number:04d}_synced.mp4")

    if speed_factor is None:
        # Video too short — loop it
        await _loop_video_to_duration(video_local_path, voice_duration, synced_video)
    else:
        # Adjust speed to match voice
        await _adjust_video_speed(video_local_path, speed_factor, voice_duration, synced_video)

    # Combine with audio
    with_audio = os.path.join(base_dir, f"scene_{scene_number:04d}_with_audio.mp4")
    await run_ffmpeg(
        "-i", synced_video,
        "-i", voice_local_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        with_audio,
        timeout=120,
    )
    safe_delete(synced_video)

    # Burn subtitles
    if subtitle_enabled:
        sub_path = os.path.join(base_dir, f"scene_{scene_number:04d}.ass")
        generate_ass_subtitle(narration_text, voice_duration, subtitle_style, sub_path)

        final_scene = os.path.join(base_dir, f"scene_{scene_number:04d}_final.mp4")
        # Escape path for FFmpeg subtitle filter
        escaped_sub = sub_path.replace("\\", "/").replace(":", "\\:")
        await run_ffmpeg(
            "-i", with_audio,
            "-vf", f"ass={escaped_sub}",
            "-c:v", "libx264",
            "-c:a", "copy",
            final_scene,
            timeout=120,
        )
        safe_delete(with_audio)
        safe_delete(sub_path)
    else:
        final_scene = with_audio

    key = get_s3_key(project_id, job_id, "scenes", f"scene_{scene_number:04d}_assembled.mp4")
    url = s3.upload_file(final_scene, key, "video/mp4")
    safe_delete(final_scene)

    log.info("Scene assembled and uploaded", url=url)
    return url


async def _loop_video_to_duration(video_path: str, target_duration: float, output_path: str) -> None:
    await run_ffmpeg(
        "-stream_loop", "-1",
        "-i", video_path,
        "-t", str(target_duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        output_path,
        timeout=120,
    )


async def _adjust_video_speed(
    video_path: str, speed_factor: float, voice_duration: float, output_path: str
) -> None:
    await run_ffmpeg(
        "-i", video_path,
        "-vf", f"setpts={1.0 / speed_factor}*PTS",
        "-t", str(voice_duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path,
        timeout=120,
    )
