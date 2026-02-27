"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "render_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_scenes", sa.Integer, nullable=False),
        sa.Column("completed_scenes", sa.Integer, server_default="0"),
        sa.Column("failed_scenes", sa.Integer, server_default="0"),
        sa.Column("settings", postgresql.JSONB, nullable=False),
        sa.Column("webhook_url", sa.String(500), nullable=True),
        sa.Column("final_video_url", sa.String(500), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.CheckConstraint("channel IN ('kenburns', 'animated')", name="channel_check"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'assembling', 'completed', 'failed', 'partial_failure')",
            name="status_check",
        ),
    )

    op.create_table(
        "scenes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("render_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("render_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("image_prompt", sa.Text, nullable=False),
        sa.Column("animation_prompt", sa.Text, nullable=True),
        sa.Column("narration_text", sa.Text, nullable=False),
        sa.Column("voice_id", sa.String(100), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("voice_url", sa.String(500), nullable=True),
        sa.Column("raw_video_url", sa.String(500), nullable=True),
        sa.Column("assembled_scene_url", sa.String(500), nullable=True),
        sa.Column("voice_duration_seconds", sa.Float, nullable=True),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("render_job_id", "scene_number", name="uq_scene_per_job"),
        sa.CheckConstraint(
            "status IN ('pending', 'generating_image', 'generating_voice', 'animating', "
            "'applying_effects', 'assembling', 'completed', 'failed')",
            name="scene_status_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("scenes")
    op.drop_table("render_jobs")
    op.drop_table("projects")
