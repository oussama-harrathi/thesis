"""blueprint_questions mapping table, reviewed status, blueprint_id on question_sets

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2025-01-01 00:00:00.000000

Changes:
  1. Add 'reviewed' value to question_status PostgreSQL enum
  2. Add blueprint_id (nullable FK) to question_sets table
  3. Create blueprint_questions mapping table
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "g2h3i4j5k6l7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add 'reviewed' to question_status enum ─────────────────────────────
    # PostgreSQL requires COMMIT before ALTER TYPE ADD VALUE inside a transaction.
    # Alembic executes each op in a transaction; use execute() with autocommit.
    op.execute("ALTER TYPE question_status ADD VALUE IF NOT EXISTS 'reviewed'")

    # ── 2. Add blueprint_id (nullable FK) to question_sets ────────────────────
    op.add_column(
        "question_sets",
        sa.Column(
            "blueprint_id",
            UUID(as_uuid=True),
            sa.ForeignKey("exam_blueprints.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_question_sets_blueprint_id",
        "question_sets",
        ["blueprint_id"],
        unique=False,
    )

    # ── 3. Create blueprint_questions mapping table ────────────────────────────
    op.create_table(
        "blueprint_questions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "blueprint_id",
            UUID(as_uuid=True),
            sa.ForeignKey("exam_blueprints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Tracks which blueprint originally owned this question before a replace
        sa.Column(
            "original_blueprint_id",
            UUID(as_uuid=True),
            sa.ForeignKey("exam_blueprints.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("blueprint_id", "question_id", name="uq_blueprint_question"),
    )
    op.create_index(
        "ix_blueprint_questions_blueprint_id",
        "blueprint_questions",
        ["blueprint_id"],
    )
    op.create_index(
        "ix_blueprint_questions_question_id",
        "blueprint_questions",
        ["question_id"],
    )


def downgrade() -> None:
    # Drop mapping table
    op.drop_index("ix_blueprint_questions_question_id", table_name="blueprint_questions")
    op.drop_index("ix_blueprint_questions_blueprint_id", table_name="blueprint_questions")
    op.drop_table("blueprint_questions")

    # Remove blueprint_id from question_sets
    op.drop_index("ix_question_sets_blueprint_id", table_name="question_sets")
    op.drop_column("question_sets", "blueprint_id")

    # NOTE: PostgreSQL does not support removing enum values directly.
    # Removing 'reviewed' from question_status is skipped in downgrade.
