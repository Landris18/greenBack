"""sources de mesure materielle

Revision ID: 8b1f4c02d7a3
Revises: 27425a907b11
Create Date: 2026-08-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8b1f4c02d7a3"
down_revision: str | None = "27425a907b11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOUVELLES_SOURCES = ("BMC", "BATTERY", "HWMON")


def upgrade() -> None:
    for source in NOUVELLES_SOURCES:
        op.execute(f"ALTER TYPE power_source ADD VALUE IF NOT EXISTS '{source}'")

    op.add_column("host", sa.Column("measurement_sources", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("host", "measurement_sources")
