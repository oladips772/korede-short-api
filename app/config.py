from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # App
    app_name: str = "korede-short-api"
    app_env: str = "production"
    app_port: int = 2000
    api_key: str

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Kie.ai
    kie_ai_api_key: str
    kie_ai_base_url: str = "https://api.kie.ai/api/v1"
    kie_ai_concurrency: int = 5

    # ElevenLabs
    elevenlabs_api_key: str
    elevenlabs_concurrency: int = 5

    # AWS S3
    s3_bucket: str
    s3_region: str = "us-east-1"
    aws_access_key_id: str
    aws_secret_access_key: str

    # Pipeline
    batch_size: int = 10
    max_retries: int = 3
    scene_failure_threshold: float = 0.5
    temp_dir: str = "/tmp/media-master"

    # FFmpeg
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    ffprobe_path: str = "/usr/bin/ffprobe"


settings = Settings()
