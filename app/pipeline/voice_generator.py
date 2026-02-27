import structlog
from app.services.elevenlabs import elevenlabs_client
from app.services.s3 import s3, get_s3_key

logger = structlog.get_logger()


async def generate_and_upload_voice(
    project_id: str,
    job_id: str,
    scene_number: int,
    narration_text: str,
    voice_id: str,
) -> tuple[str, float]:
    """Generate voiceover via ElevenLabs and upload to S3. Returns (s3_url, duration_seconds)."""
    log = logger.bind(job_id=job_id, scene_number=scene_number)
    log.info("Generating voiceover")

    audio_bytes, duration = await elevenlabs_client.generate_speech(
        text=narration_text,
        voice_id=voice_id,
    )

    key = get_s3_key(project_id, job_id, "voices", f"scene_{scene_number:04d}.mp3")
    url = s3.upload_bytes(audio_bytes, key, "audio/mpeg")
    log.info("Voice uploaded to S3", url=url, duration=duration)
    return url, duration
