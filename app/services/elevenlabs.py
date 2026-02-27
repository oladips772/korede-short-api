import io
import asyncio
import structlog
import httpx
from mutagen.mp3 import MP3

from app.config import settings
from app.utils.retry import async_retry

logger = structlog.get_logger()

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.elevenlabs_concurrency)
    return _semaphore


class ElevenLabsClient:
    def __init__(self):
        self.api_key = settings.elevenlabs_api_key
        self.base_url = ELEVENLABS_BASE_URL

    @async_retry(max_attempts=3, retryable_status_codes={429, 500, 502, 503, 504})
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128",
    ) -> tuple[bytes, float]:
        """Generate speech. Returns (audio_bytes, duration_seconds)."""
        async with get_semaphore():
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/text-to-speech/{voice_id}",
                    headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
                    params={"output_format": output_format},
                    json={
                        "text": text,
                        "model_id": model_id,
                    },
                )
                response.raise_for_status()
                audio_bytes = response.content
                duration = self._get_mp3_duration(audio_bytes)
                logger.debug(
                    "ElevenLabs TTS generated",
                    voice_id=voice_id,
                    duration=duration,
                    text_length=len(text),
                )
                return audio_bytes, duration

    def _get_mp3_duration(self, audio_bytes: bytes) -> float:
        try:
            audio = MP3(io.BytesIO(audio_bytes))
            return audio.info.length
        except Exception:
            # Fallback: estimate ~150 words per minute
            word_count = len(audio_bytes.decode("latin-1", errors="ignore").split())
            return max(1.0, word_count / 2.5)


elevenlabs_client = ElevenLabsClient()
