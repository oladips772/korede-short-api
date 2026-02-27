import io
import asyncio
import structlog
import httpx
from mutagen.mp3 import MP3

from app.config import settings
from app.utils.retry import async_retry

logger = structlog.get_logger()

_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.elevenlabs_concurrency)
    return _semaphore


class ElevenLabsClient:
    """
    ElevenLabs TTS routed through the Kie.ai API.

    Task pattern:
      1. POST /jobs/createTask with model elevenlabs/text-to-speech-turbo-2-5
      2. Poll GET /jobs/recordInfo?taskId=... until state == 'success'
      3. Download audio from resultJson.resultUrls[0]
    """

    def __init__(self):
        self.api_key = settings.kie_ai_api_key
        self.base_url = settings.kie_ai_base_url

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @async_retry(max_attempts=3, retryable_status_codes={429, 500, 502, 503, 504})
    async def generate_speech(
        self,
        text: str,
        voice_id: str,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0,
        speed: float = 1,
    ) -> tuple[bytes, float]:
        """Generate speech via Kie.ai ElevenLabs endpoint. Returns (audio_bytes, duration_seconds)."""
        async with get_semaphore():
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "model": "elevenlabs/text-to-speech-turbo-2-5",
                    "input": {
                        "text": text,
                        "voice": voice_id,
                        "stability": stability,
                        "similarity_boost": similarity_boost,
                        "style": style,
                        "speed": speed,
                        "timestamps": False,
                    },
                }

                response = await client.post(
                    f"{self.base_url}/jobs/createTask",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                resp_data = response.json()

                task_id = (
                    resp_data.get("data", {}).get("taskId")
                    or resp_data.get("taskId")
                )
                if not task_id:
                    raise ValueError(f"No taskId in Kie.ai TTS response: {resp_data}")

                task_result = await self._poll_task(task_id, client=client)
                audio_url = self._extract_url(task_result)

                audio_response = await client.get(audio_url, timeout=60.0)
                audio_response.raise_for_status()
                audio_bytes = audio_response.content

                duration = self._get_mp3_duration(audio_bytes)
                logger.debug(
                    "TTS generated via Kie.ai",
                    voice_id=voice_id,
                    duration=duration,
                    text_length=len(text),
                )
                return audio_bytes, duration

    def _extract_url(self, task_data: dict) -> str:
        import json
        result_json_str = task_data.get("resultJson")
        if not result_json_str:
            raise ValueError(f"No resultJson in Kie.ai TTS result: {task_data}")
        result = json.loads(result_json_str)
        urls = result.get("resultUrls", [])
        if not urls:
            raise ValueError(f"No resultUrls in Kie.ai TTS resultJson: {result}")
        return urls[0]

    async def _poll_task(
        self,
        task_id: str,
        client: httpx.AsyncClient,
        max_wait: int = 120,
        interval: int = 3,
    ) -> dict:
        elapsed = 0
        while elapsed < max_wait:
            response = await client.get(
                f"{self.base_url}/jobs/recordInfo",
                headers=self._headers(),
                params={"taskId": task_id},
            )
            response.raise_for_status()
            resp_data = response.json()
            data = resp_data.get("data", resp_data)
            state = data.get("state", "").lower()

            logger.debug("Kie.ai TTS poll", task_id=task_id, state=state, elapsed=elapsed)

            if state == "success":
                return data
            if state in ("failed", "error"):
                raise RuntimeError(
                    f"Kie.ai TTS task {task_id} failed: {data.get('failMsg', 'unknown')} "
                    f"(code: {data.get('failCode')})"
                )

            await asyncio.sleep(interval)
            elapsed += interval

        raise TimeoutError(f"Kie.ai TTS task {task_id} timed out after {max_wait}s")

    def _get_mp3_duration(self, audio_bytes: bytes) -> float:
        try:
            audio = MP3(io.BytesIO(audio_bytes))
            return audio.info.length
        except Exception:
            word_count = len(audio_bytes.decode("latin-1", errors="ignore").split())
            return max(1.0, word_count / 2.5)


elevenlabs_client = ElevenLabsClient()
