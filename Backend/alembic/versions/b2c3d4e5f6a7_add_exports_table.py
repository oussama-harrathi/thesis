"""add_exports_table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-24 00:00:00.000000

Adds:
  - exports table (Export model)
    - export_type enum: exam_pdf | answer_key_pdf | exam_tex | answer_key_tex
    - export_status enum: pending | completed | failed
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL for everything in this migration to avoid SQLAlchemy
    # auto-creating enum types that may already exist from a previous
    # app-startup (create_all) call.
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE export_type AS ENUM
            ('exam_pdf', 'answer_key_pdf', 'exam_tex', 'answer_key_tex');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE export_status AS ENUM ('pending', 'completed', 'failed');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS exports (
            id          UUID            NOT NULL PRIMARY KEY,
            exam_id     UUID            NOT NULL
                        REFERENCES exams(id) ON DELETE CASCADE,
            export_type export_type     NOT NULL,
            status      export_status   NOT NULL DEFAULT 'pending',
            file_path   TEXT,
            error_message TEXT,
            created_at  TIMESTAMP       NOT NULL DEFAULT now(),
            updated_at  TIMESTAMP       NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_exports_exam_id ON exports(exam_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_exports_exam_id")
    op.execute("DROP TABLE IF EXISTS exports")
    op.execute("DROP TYPE IF EXISTS export_status")
    op.execute("DROP TYPE IF EXISTS export_type")

