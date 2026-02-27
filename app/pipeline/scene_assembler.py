import os
import structlog
from app.ffmpeg.commands import run_ffmpeg, get_video_duration
from app.ffmpeg.subtitles import generate_ass_subtitle
from app.services.s3 import s3, get_s3_key
from app.utils.timing import calculate_speed_factor
from app.utils.cleanup import safe_delete
from app.config import settings

logger = structlog.get_logger()

# Shared quality flags used on every encode step so all scene files are
# bit-for-bit compatible for the concat demuxer.
_VIDEO_ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
_AUDIO_ENCODE = ["-c:a", "aac", "-b:a", "192k"]
_FASTSTART    = ["-movflags", "+faststart"]


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
    Assemble a single scene: sync video to audio, optionally burn subtitles.
    Returns the S3 URL of the assembled scene.

    voice_duration must be the ffprobe-measured actual duration of voice_local_path.
    It is used here only for subtitle timing.  All video sizing decisions are
    re-derived from the actual files via ffprobe.
    """
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info("Assembling scene")

    base_dir = temp_dir or os.path.join(settings.temp_dir, job_id, "scenes")
    os.makedirs(base_dir, exist_ok=True)

    video_duration = await get_video_duration(video_local_path)
    # Re-measure the audio from the file — this is the authoritative duration.
    actual_audio_duration = await get_video_duration(voice_local_path)

    log.info(
        "Scene durations",
        video=video_duration,
        audio=actual_audio_duration,
    )

    speed_factor = calculate_speed_factor(video_duration, actual_audio_duration)
    synced_video = os.path.join(base_dir, f"scene_{scene_number:04d}_synced.mp4")

    if speed_factor is None:
        # Video far too short — loop it to fill the full narration
        await _loop_video_to_duration(video_local_path, actual_audio_duration, synced_video)
    else:
        # Stretch or compress video to match narration length exactly
        await _adjust_video_speed(video_local_path, speed_factor, actual_audio_duration, synced_video)

    # Combine video + audio (and subtitles if enabled) in a single FFmpeg pass.
    # Using a single pass avoids a double re-encode of the video stream.
    final_scene = os.path.join(base_dir, f"scene_{scene_number:04d}_final.mp4")

    if subtitle_enabled:
        sub_path = os.path.join(base_dir, f"scene_{scene_number:04d}.ass")
        generate_ass_subtitle(narration_text, actual_audio_duration, subtitle_style, sub_path)
        escaped_sub = sub_path.replace("\\", "/").replace(":", "\\:")

        # One pass: re-encode video (to burn subtitles) + mux audio
        await run_ffmpeg(
            "-i", synced_video,
            "-i", voice_local_path,
            "-vf", f"ass={escaped_sub}",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", str(actual_audio_duration),
            *_VIDEO_ENCODE,
            *_AUDIO_ENCODE,
            *_FASTSTART,
            final_scene,
            timeout=180,
        )
        safe_delete(sub_path)
    else:
        # No subtitles — copy the already-encoded video stream, only mux audio.
        # synced_video is already libx264/yuv420p from the adjust/loop step.
        await run_ffmpeg(
            "-i", synced_video,
            "-i", voice_local_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", str(actual_audio_duration),
            "-c:v", "copy",
            *_AUDIO_ENCODE,
            *_FASTSTART,
            final_scene,
            timeout=180,
        )

    safe_delete(synced_video)

    key = get_s3_key(project_id, job_id, "scenes", f"scene_{scene_number:04d}_assembled.mp4")
    url = s3.upload_file(final_scene, key, "video/mp4")
    safe_delete(final_scene)

    log.info("Scene assembled and uploaded", url=url, duration=actual_audio_duration)
    return url


async def _loop_video_to_duration(
    video_path: str, target_duration: float, output_path: str
) -> None:
    """Loop a video clip until it reaches target_duration."""
    await run_ffmpeg(
        "-stream_loop", "-1",
        "-i", video_path,
        "-t", str(target_duration),
        *_VIDEO_ENCODE,
        *_FASTSTART,
        output_path,
        timeout=180,
    )


async def _adjust_video_speed(
    video_path: str, speed_factor: float, target_duration: float, output_path: str
) -> None:
    """
    Stretch or compress video to target_duration by adjusting PTS.
    -stream_loop -1 prevents the input from running out before the -t trim fires
    when the PTS-adjusted clip would be marginally shorter than target_duration.
    -an discards any pre-existing audio track; audio is added later.
    """
    await run_ffmpeg(
        "-stream_loop", "-1",
        "-i", video_path,
        "-vf", f"setpts={1.0 / speed_factor:.6f}*PTS",
        "-t", str(target_duration),
        "-an",
        *_VIDEO_ENCODE,
        *_FASTSTART,
        output_path,
        timeout=180,
    )
