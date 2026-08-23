"""plafond de puissance a vide

Revision ID: 9c2e5d31f804
Revises: 8b1f4c02d7a3
Create Date: 2026-08-16 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c2e5d31f804"
down_revision: str | None = "8b1f4c02d7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "green_config",
        sa.Column("max_idle_ratio", sa.Float(), nullable=False, server_default="0.7"),
    )


def downgrade() -> None:
    op.drop_column("green_config", "max_idle_ratio")
