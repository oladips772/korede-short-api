"""Seed the database with a sample render job for local testing."""
import asyncio
import httpx
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "your-api-secret-key-here")


async def seed():
    payload = {
        "project_name": "Test Project — Seed",
        "channel": "kenburns",
        "webhook_url": None,
        "settings": {
            "resolution": "1080x1920",
            "fps": 30,
            "background_music": None,
            "background_music_volume": 0.15,
            "subtitle_enabled": True,
            "subtitle_style": "bold_center",
            "transition_type": "crossfade",
            "transition_duration_ms": 500,
        },
        "scenes": [
            {
                "scene_number": i,
                "image_prompt": f"A stunning scene number {i}, cinematic, 8k quality",
                "animation_prompt": None,
                "narration_text": f"This is the narration for scene {i}. It describes what is happening.",
                "voice_id": "pNInz6obpgDQGcFmaJgB",
            }
            for i in range(1, 4)
        ],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_URL}/api/v1/render",
            json=payload,
            headers={"X-API-Key": API_KEY},
        )
        resp.raise_for_status()
        data = resp.json()
        print("Render job created:", data)


if __name__ == "__main__":
    asyncio.run(seed())
