from __future__ import annotations
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl, field_validator


class RenderSettings(BaseModel):
    aspect_ratio: str = "16:9"
    resolution: str = "1K"
    fps: int = 30
    background_music: Optional[str] = None
    background_music_volume: float = Field(default=0.15, ge=0.0, le=1.0)

    @field_validator("background_music")
    @classmethod
    def validate_background_music(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Accept full HTTP/HTTPS URLs (Cloudinary, S3 presigned, any CDN)
        if v.startswith(("http://", "https://")):
            return v
        # Accept S3 keys — must be a non-empty string that doesn't look like a path typo
        if v.strip():
            return v.strip()
        raise ValueError("background_music must be an HTTP/HTTPS URL or a non-empty S3 key")
    subtitle_enabled: bool = True
    subtitle_style: Literal["bold_center", "bottom_bar", "minimal"] = "bold_center"
    transition_type: Literal["crossfade", "cut"] = "crossfade"
    transition_duration_ms: int = Field(default=500, ge=0, le=2000)


class ScenePayload(BaseModel):
    scene_number: int = Field(..., ge=1)
    image_prompt: str
    animation_prompt: Optional[str] = None
    narration_text: str
    voice_id: str


class RenderRequest(BaseModel):
    project_name: str
    channel: Literal["kenburns", "animated"]
    webhook_url: Optional[str] = None
    settings: RenderSettings = Field(default_factory=RenderSettings)
    scenes: list[ScenePayload] = Field(..., min_length=1)


class RenderResponse(BaseModel):
    job_id: UUID
    status: str
    total_scenes: int
    monitor_url: str
    message: str


class SceneStatusItem(BaseModel):
    scene_number: int
    status: str
    assembled_scene_url: Optional[str] = None


class RenderProgress(BaseModel):
    total_scenes: int
    completed_scenes: int
    failed_scenes: int
    percentage: float


class RenderStatusResponse(BaseModel):
    job_id: UUID
    status: str
    channel: str
    progress: RenderProgress
    final_video_url: Optional[str] = None
    estimated_completion_minutes: Optional[float] = None
    scenes: list[SceneStatusItem]


class RetryRequest(BaseModel):
    scene_numbers: Optional[list[int]] = None
    retry_all_failed: bool = False
