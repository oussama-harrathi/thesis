"""add_blueprint_id_to_jobs

Revision ID: f966849e4638
Revises: bfd15fe0bfaf
Create Date: 2026-02-24 00:00:00.000000

Adds blueprint_id FK column to the jobs table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f966849e4638"
down_revision: Union[str, Sequence[str], None] = "bfd15fe0bfaf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add blueprint_id column + FK + index to jobs."""
    op.add_column(
        "jobs",
        sa.Column("blueprint_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_jobs_blueprint_id",
        "jobs",
        "exam_blueprints",
        ["blueprint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_jobs_blueprint_id"),
        "jobs",
        ["blueprint_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove blueprint_id column from jobs."""
    op.drop_index(op.f("ix_jobs_blueprint_id"), table_name="jobs")
    op.drop_constraint("fk_jobs_blueprint_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "blueprint_id")
