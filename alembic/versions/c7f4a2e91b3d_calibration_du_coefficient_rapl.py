"""calibration du coefficient RAPL

Revision ID: c7f4a2e91b3d
Revises: b5e8f27c419d
Create Date: 2026-08-19 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7f4a2e91b3d"
down_revision: str | None = "b5e8f27c419d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("green_config", sa.Column("calibration_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("green_config", "calibration_note")
