"""statut conteneur absent

Revision ID: a4d7e91b06c2
Revises: 9c2e5d31f804
Create Date: 2026-08-17 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4d7e91b06c2"
down_revision: str | None = "9c2e5d31f804"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE container_status ADD VALUE IF NOT EXISTS 'ABSENT'")


def downgrade() -> None:
    pass
