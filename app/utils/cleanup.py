import os
import shutil
import structlog

logger = structlog.get_logger()


def cleanup_job_temp_dir(job_id: str, temp_base: str = "/tmp/media-master") -> None:
    """Remove all temp files for a job."""
    job_dir = os.path.join(temp_base, job_id)
    if os.path.exists(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.info("Cleaned up temp dir", job_id=job_id, path=job_dir)


def ensure_job_dirs(job_id: str, temp_base: str = "/tmp/media-master") -> dict[str, str]:
    """Create and return job-specific temp subdirectories."""
    base = os.path.join(temp_base, job_id)
    dirs = {
        "root": base,
        "images": os.path.join(base, "images"),
        "voices": os.path.join(base, "voices"),
        "videos": os.path.join(base, "videos"),
        "scenes": os.path.join(base, "scenes"),
        "final": os.path.join(base, "final"),
        "subtitles": os.path.join(base, "subtitles"),
    }
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


def safe_delete(path: str) -> None:
    """Delete a file if it exists, silently."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        logger.warning("Failed to delete temp file", path=path, error=str(e))
