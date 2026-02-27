import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, func, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base


class RenderJob(Base):
    __tablename__ = "render_jobs"

    __table_args__ = (
        CheckConstraint("channel IN ('kenburns', 'animated')", name="channel_check"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'assembling', 'completed', 'failed', 'partial_failure')",
            name="status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    total_scenes: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_scenes: Mapped[int] = mapped_column(Integer, default=0)
    failed_scenes: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    final_video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="render_jobs")
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene", back_populates="render_job", cascade="all, delete-orphan"
    )
