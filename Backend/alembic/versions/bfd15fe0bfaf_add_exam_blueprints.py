"""add_exam_blueprints

Revision ID: bfd15fe0bfaf
Revises: 7d140e5b2934
Create Date: 2026-02-24 00:00:00.000000

Adds the exam_blueprints table (Phase 9 — Blueprint model).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "bfd15fe0bfaf"
down_revision: Union[str, Sequence[str], None] = "7d140e5b2934"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create exam_blueprints table."""
    op.create_table(
        "exam_blueprints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Serialised BlueprintConfig JSON validated by Pydantic on write/read.
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_exam_blueprints_course_id"),
        "exam_blueprints",
        ["course_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop exam_blueprints table."""
    op.drop_index(op.f("ix_exam_blueprints_course_id"), table_name="exam_blueprints")
    op.drop_table("exam_blueprints")
