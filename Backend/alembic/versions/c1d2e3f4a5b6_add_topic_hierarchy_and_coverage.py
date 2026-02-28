"""add_topic_hierarchy_and_coverage

Adds these columns to the *topics* table:

    parent_topic_id  UUID nullable  – self-referential FK for hierarchy
    level            VARCHAR(20)    – CHAPTER / SECTION / SUBSECTION
    source           VARCHAR(32)    – AUTO / TOC / MANUAL  (default: AUTO)
    coverage_score   FLOAT          – fraction of course chunks mapped to topic

Revision ID: c1d2e3f4a5b6
Revises: 7d140e5b2934
Create Date: 2026-02-27 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "topics",
        sa.Column(
            "parent_topic_id",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.add_column(
        "topics",
        sa.Column("level", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "topics",
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=True,
            server_default="AUTO",
        ),
    )
    op.add_column(
        "topics",
        sa.Column("coverage_score", sa.Float(), nullable=True),
    )

    op.create_index(
        "ix_topics_parent_topic_id",
        "topics",
        ["parent_topic_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_topics_parent_topic_id",
        "topics",
        "topics",
        ["parent_topic_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_topics_parent_topic_id", "topics", type_="foreignkey")
    op.drop_index("ix_topics_parent_topic_id", table_name="topics")
    op.drop_column("topics", "coverage_score")
    op.drop_column("topics", "source")
    op.drop_column("topics", "level")
    op.drop_column("topics", "parent_topic_id")
