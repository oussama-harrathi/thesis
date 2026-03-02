"""diversity_and_blacklist

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-03-01 00:00:00.000000

Adds:
  - questions.fingerprint   — SHA-256 of normalised stem for exact-duplicate detection
  - questions.embedding     — vector(384) for semantic near-duplicate detection
  - questions.generation_run_id — UUID of the question_set_id (generation run)
  - question_blacklist table — course-scoped rejected-question memory
"""

from typing import Sequence, Union

import sqlalchemy as sa
import pgvector.sqlalchemy
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add diversity / rejection-memory columns and table."""

    # ── Extend questions table ────────────────────────────────────────────
    op.add_column(
        "questions",
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "questions",
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(384),
            nullable=True,
        ),
    )
    op.add_column(
        "questions",
        sa.Column("generation_run_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f("ix_questions_fingerprint"),
        "questions",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_questions_generation_run_id"),
        "questions",
        ["generation_run_id"],
        unique=False,
    )

    # ── question_blacklist table ──────────────────────────────────────────
    op.create_table(
        "question_blacklist",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.Vector(384),
            nullable=True,
        ),
        sa.Column("original_question_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_question_blacklist_course_id"),
        "question_blacklist",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_blacklist_fingerprint"),
        "question_blacklist",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_blacklist_original_question_id"),
        "question_blacklist",
        ["original_question_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove diversity / rejection-memory additions."""
    # Drop blacklist table
    op.drop_index(
        op.f("ix_question_blacklist_original_question_id"),
        table_name="question_blacklist",
    )
    op.drop_index(
        op.f("ix_question_blacklist_fingerprint"),
        table_name="question_blacklist",
    )
    op.drop_index(
        op.f("ix_question_blacklist_course_id"),
        table_name="question_blacklist",
    )
    op.drop_table("question_blacklist")

    # Drop new columns from questions
    op.drop_index(
        op.f("ix_questions_generation_run_id"), table_name="questions"
    )
    op.drop_index(
        op.f("ix_questions_fingerprint"), table_name="questions"
    )
    op.drop_column("questions", "generation_run_id")
    op.drop_column("questions", "embedding")
    op.drop_column("questions", "fingerprint")
