"""Add chunk_type and chunk_type_score columns to chunks table.

Revision ID: f1a2b3c4d5e6
Revises:     e3f4a5b6c7d8
Create Date: 2025-01-01 00:00:00.000000

Adds a deterministic content-classification column (chunk_type) to each chunk
so that retrieval can hard-filter out admin/boilerplate chunks at the DB level
without any post-query Python filtering overhead.

Four types (matches ChunkType enum in app.utils.chunk_classifier):
  instructional           — main teaching / explanation content  (default)
  exercise                — primarily problem / exercise statements
  references_boilerplate  — references, bibliography, index, repeated headers
  admin_assessment        — mark allocations, paper structure, assessment rules

chunk_type_score stores the classifier's confidence score for audit purposes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum values must match ChunkType in app.utils.chunk_classifier exactly.
_ENUM_VALUES = (
    "instructional",
    "exercise",
    "references_boilerplate",
    "admin_assessment",
)
_ENUM_NAME = "chunktype"


def upgrade() -> None:
    # 1. Create the PostgreSQL enum type.
    # Using native CREATE TYPE so we can reference it cleanly; also avoids
    # the SQLAlchemy Enum 'create_constraint' path which requires the type
    # to already exist when the column is added.
    op.execute(
        f"CREATE TYPE {_ENUM_NAME} AS ENUM ("
        + ", ".join(f"'{v}'" for v in _ENUM_VALUES)
        + ")"
    )

    # 2. Add chunk_type column (non-null, default 'instructional').
    op.add_column(
        "chunks",
        sa.Column(
            "chunk_type",
            sa.Enum(*_ENUM_VALUES, name=_ENUM_NAME, create_type=False),
            nullable=False,
            server_default="instructional",
        ),
    )

    # 3. Add chunk_type_score column (integer confidence score from classifier).
    op.add_column(
        "chunks",
        sa.Column(
            "chunk_type_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # 4. Create index on chunk_type for efficient WHERE chunk_type NOT IN (...)
    #    filtering during retrieval.
    op.create_index(
        "ix_chunks_chunk_type",
        "chunks",
        ["chunk_type"],
    )


def downgrade() -> None:
    # 1. Drop the index.
    op.drop_index("ix_chunks_chunk_type", table_name="chunks")

    # 2. Drop the columns.
    op.drop_column("chunks", "chunk_type_score")
    op.drop_column("chunks", "chunk_type")

    # 3. Drop the enum type.
    op.execute(f"DROP TYPE IF EXISTS {_ENUM_NAME}")
