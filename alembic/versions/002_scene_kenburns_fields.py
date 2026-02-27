"""Add ken_burns_keypoints and pan_direction to scenes

Revision ID: 002
Revises: 001
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scenes",
        sa.Column("pan_direction", sa.String(50), nullable=True),
    )
    op.add_column(
        "scenes",
        sa.Column("ken_burns_keypoints", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scenes", "ken_burns_keypoints")
    op.drop_column("scenes", "pan_direction")
