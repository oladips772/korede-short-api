import asyncio
import json
import structlog
import httpx

from app.config import settings
from app.utils.retry import async_retry

logger = structlog.get_logger()

_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.kie_ai_concurrency)
    return _semaphore


class KieAIClient:
    """
    Kie.ai API client for image generation and image-to-video animation.

    Task pattern:
      1. POST /jobs/createTask → get taskId
      2. Poll GET /jobs/recordInfo?taskId=... until state == 'success'
      3. Parse resultJson to extract the image/video URL
    """

    def __init__(self):
        self.api_key = settings.kie_ai_api_key
        self.base_url = settings.kie_ai_base_url

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _extract_image_url(self, task_data: dict) -> str:
        """Parse resultJson string and return the first result URL."""
        result_json_str = task_data.get("resultJson")
        if not result_json_str:
            raise ValueError(f"No resultJson in Kie.ai task result: {task_data}")
        result = json.loads(result_json_str)
        urls = result.get("resultUrls", [])
        if not urls:
            raise ValueError(f"No resultUrls in Kie.ai resultJson: {result}")
        return urls[0]

    @async_retry(max_attempts=3, retryable_status_codes={429, 500, 502, 503, 504})
    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        resolution: str = "1K",
    ) -> bytes:
        """Generate an image from a text prompt. Returns image bytes."""
        async with get_semaphore():
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "model": "flux-2/pro-text-to-image",
                    "input": {
                        "prompt": prompt,
                        "aspect_ratio": aspect_ratio,
                        "resolution": resolution,
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
                    raise ValueError(f"No taskId in Kie.ai createTask response: {resp_data}")

                task_result = await self.poll_task(task_id, client=client)
                image_url = self._extract_image_url(task_result)

                img_response = await client.get(image_url, timeout=60.0)
                img_response.raise_for_status()
                return img_response.content

    @async_retry(max_attempts=3, retryable_status_codes={429, 500, 502, 503, 504})
    async def animate_image(
        self,
        image_url: str,
        animation_prompt: str,
        duration_seconds: float = 5.0,
        resolution: str = "1080p",
    ) -> bytes:
        """Convert a static image to an animated video clip. Returns video bytes."""
        async with get_semaphore():
            async with httpx.AsyncClient(timeout=300.0) as client:
                payload = {
                    "model": "bytedance/v1-pro-fast-image-to-video",
                    "input": {
                        "prompt": animation_prompt,
                        "image_url": image_url,
                        "resolution": resolution,
                        "duration": str(max(1, round(duration_seconds))),
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
                    raise ValueError(f"No taskId in Kie.ai animate response: {resp_data}")

                task_result = await self.poll_task(task_id, client=client, max_wait=300)
                video_url = self._extract_image_url(task_result)

                vid_response = await client.get(video_url, timeout=120.0)
                vid_response.raise_for_status()
                return vid_response.content

    async def poll_task(
        self,
        task_id: str,
        client: httpx.AsyncClient | None = None,
        max_wait: int = 300,
        interval: int = 5,
    ) -> dict:
        """Poll GET /jobs/recordInfo?taskId=... until state == 'success' or timeout."""
        own_client = client is None
        if own_client:
            client = httpx.AsyncClient(timeout=30.0)

        try:
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

                logger.debug("Kie.ai task poll", task_id=task_id, state=state, elapsed=elapsed)

                if state == "success":
                    return data
                if state in ("failed", "error"):
                    raise RuntimeError(
                        f"Kie.ai task {task_id} failed: {data.get('failMsg', 'unknown')} "
                        f"(code: {data.get('failCode')})"
                    )

                await asyncio.sleep(interval)
                elapsed += interval

            raise TimeoutError(f"Kie.ai task {task_id} timed out after {max_wait}s")
        finally:
            if own_client:
                await client.aclose()


kie_ai_client = KieAIClient()
