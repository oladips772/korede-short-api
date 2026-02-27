import os
import structlog
import httpx
from app.ffmpeg.transitions import apply_crossfade_concat
from app.ffmpeg.audio import mix_background_music, normalize_audio
from app.services.s3 import s3, get_s3_key
from app.utils.cleanup import safe_delete
from app.config import settings

logger = structlog.get_logger()


async def resolve_music_source(music_value: str, temp_dir: str) -> str:
    """
    Resolve a background_music value to a local file path for FFmpeg.

    - If music_value starts with http:// or https://, downloads the file via httpx.
    - Otherwise treats it as an S3 key and downloads from the configured bucket.

    Returns the local temp file path.
    Raises on download failure or timeout.
    """
    os.makedirs(temp_dir, exist_ok=True)
    local_path = os.path.join(temp_dir, "background_music.mp3")

    if music_value.startswith(("http://", "https://")):
        logger.debug("Downloading music from URL", url=music_value)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(music_value)
            response.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(response.content)
        logger.debug("Music downloaded from URL", local_path=local_path)
    else:
        logger.debug("Downloading music from S3", key=music_value)
        s3.download_file(music_value, local_path)
        logger.debug("Music downloaded from S3", local_path=local_path)

    return local_path


async def assemble_final_video(
    project_id: str,
    job_id: str,
    assembled_scene_urls: list[str],
    job_settings: dict,
    temp_base: str | None = None,
) -> str:
    """
    Download all assembled scene files, concatenate them, add background music,
    normalize audio, and upload the final video to S3.
    Returns the final S3 URL.
    """
    log = logger.bind(job_id=job_id)
    log.info("Assembling final video", scene_count=len(assembled_scene_urls))

    base_dir = temp_base or os.path.join(settings.temp_dir, job_id, "final")
    os.makedirs(base_dir, exist_ok=True)

    # Download all assembled scenes locally
    local_scene_paths = []
    for i, url in enumerate(assembled_scene_urls):
        key = _url_to_key(url)
        local_path = os.path.join(base_dir, f"scene_{i+1:04d}.mp4")
        s3.download_file(key, local_path)
        local_scene_paths.append(local_path)

    # Concatenate
    concat_output = os.path.join(base_dir, "concat_output.mp4")
    await apply_crossfade_concat(
        local_scene_paths,
        concat_output,
        transition_duration_ms=job_settings.get("transition_duration_ms", 500),
    )

    for p in local_scene_paths:
        safe_delete(p)

    # Add background music if specified
    music_source = job_settings.get("background_music")
    local_music_path = None
    if music_source:
        try:
            local_music_path = await resolve_music_source(music_source, base_dir)
            with_music = os.path.join(base_dir, "with_music.mp4")
            await mix_background_music(
                concat_output,
                local_music_path,
                with_music,
                music_volume=job_settings.get("background_music_volume", 0.15),
            )
            safe_delete(concat_output)
            concat_output = with_music
        except Exception as e:
            log.warning("Background music failed, continuing without it", error=str(e))
        finally:
            if local_music_path:
                safe_delete(local_music_path)

    # Normalize audio
    normalized = os.path.join(base_dir, "final_normalized.mp4")
    await normalize_audio(concat_output, normalized)
    safe_delete(concat_output)

    # Upload to S3
    key = get_s3_key(project_id, job_id, "final", "final_output.mp4")
    url = s3.upload_file(normalized, key, "video/mp4")
    safe_delete(normalized)

    log.info("Final video uploaded", url=url)
    return url


def _url_to_key(s3_url: str) -> str:
    """Extract S3 key from a full S3 URL."""
    # Format: https://{bucket}.s3.amazonaws.com/{key}
    parts = s3_url.split(".s3.amazonaws.com/", 1)
    if len(parts) == 2:
        return parts[1]
    raise ValueError(f"Cannot parse S3 URL: {s3_url}")
