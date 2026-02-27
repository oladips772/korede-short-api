import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, func, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class Scene(Base):
    __tablename__ = "scenes"

    __table_args__ = (
        UniqueConstraint("render_job_id", "scene_number", name="uq_scene_per_job"),
        CheckConstraint(
            "status IN ('pending', 'generating_image', 'generating_voice', 'animating', "
            "'applying_effects', 'assembling', 'completed', 'failed')",
            name="scene_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    render_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("render_jobs.id", ondelete="CASCADE"), nullable=False
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    # Input data
    image_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    animation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    narration_text: Mapped[str] = mapped_column(Text, nullable=False)
    voice_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Ken Burns motion control (kenburns channel only)
    pan_direction: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ken_burns_keypoints: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Output artifacts (S3 URLs)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    voice_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    assembled_scene_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Metadata
    voice_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    render_job: Mapped["RenderJob"] = relationship("RenderJob", back_populates="scenes")
