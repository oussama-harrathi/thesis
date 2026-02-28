"""add_page_range_to_chunks

Add page_start and page_end columns to the chunks table so that
topic-to-chunk mapping can be done by page range when PDFs have
a Table of Contents with page numbers.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-02-27 01:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("page_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "chunks",
        sa.Column("page_end", sa.Integer(), nullable=True),
    )
    op.create_index("ix_chunks_page_start", "chunks", ["page_start"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chunks_page_start", table_name="chunks")
    op.drop_column("chunks", "page_end")
    op.drop_column("chunks", "page_start")
