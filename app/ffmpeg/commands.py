import asyncio
import structlog
from app.config import settings

logger = structlog.get_logger()


async def run_ffmpeg(*args: str, timeout: int = 300) -> None:
    """Run an FFmpeg command asynchronously, raising on non-zero exit."""
    cmd = [settings.ffmpeg_path, "-y", *args]
    logger.info("FFmpeg command", cmd=" ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"FFmpeg timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed (exit {proc.returncode}):\n{stderr.decode()}"
        )


async def run_ffprobe(*args: str) -> str:
    """Run ffprobe and return stdout."""
    cmd = [settings.ffprobe_path, *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{stderr.decode()}")
    return stdout.decode().strip()


async def get_video_duration(path: str) -> float:
    """Return duration of a video file in seconds."""
    output = await run_ffprobe(
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    )
    return float(output)
