"""add detected_subject to courses

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("detected_subject", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "detected_subject")
