"""add_exams_and_exam_questions

Revision ID: a1b2c3d4e5f6
Revises: f966849e4638
Create Date: 2026-02-24 00:00:00.000000

Adds:
  - exams table
  - exam_questions table (ordered question slots with per-question points)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f966849e4638"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── exams ─────────────────────────────────────────────────────
    op.create_table(
        "exams",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "blueprint_id",
            UUID(as_uuid=True),
            sa.ForeignKey("exam_blueprints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("total_points", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_exams_blueprint_id", "exams", ["blueprint_id"])
    op.create_index("ix_exams_course_id", "exams", ["course_id"])

    # ── exam_questions ────────────────────────────────────────────
    op.create_table(
        "exam_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exam_id",
            UUID(as_uuid=True),
            sa.ForeignKey("exams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False, server_default="1"),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=True),
    )
    op.create_index("ix_exam_questions_exam_id", "exam_questions", ["exam_id"])
    op.create_index("ix_exam_questions_question_id", "exam_questions", ["question_id"])


def downgrade() -> None:
    op.drop_table("exam_questions")
    op.drop_table("exams")
