import subprocess
from fastapi import APIRouter
import redis.asyncio as aioredis
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal

router = APIRouter()


@router.get("/health")
async def health_check():
    result = {
        "status": "healthy",
        "service": settings.app_name,
        "env": settings.app_env,
        "checks": {},
    }

    # FFmpeg version
    try:
        proc = subprocess.run(
            [settings.ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
        result["checks"]["ffmpeg"] = {"status": "ok", "version": first_line}
    except Exception as e:
        result["checks"]["ffmpeg"] = {"status": "error", "detail": str(e)}
        result["status"] = "degraded"

    # Redis
    try:
        async with aioredis.from_url(settings.redis_url) as r:
            await r.ping()
        result["checks"]["redis"] = {"status": "ok"}
    except Exception as e:
        result["checks"]["redis"] = {"status": "error", "detail": str(e)}
        result["status"] = "degraded"

    # Database
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        result["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        result["checks"]["database"] = {"status": "error", "detail": str(e)}
        result["status"] = "degraded"

    return result
