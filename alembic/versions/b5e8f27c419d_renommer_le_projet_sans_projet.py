"""renommer le projet sans-projet

Revision ID: b5e8f27c419d
Revises: a4d7e91b06c2
Create Date: 2026-08-18 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5e8f27c419d"
down_revision: str | None = "a4d7e91b06c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANCIEN = "sans-projet"
NOUVEAU = "Hors projet"


def upgrade() -> None:
    op.execute(
        f"UPDATE project SET name = '{NOUVEAU}' "
        f"WHERE name = '{ANCIEN}' "
        f"AND NOT EXISTS (SELECT 1 FROM project p2 WHERE p2.name = '{NOUVEAU}')"
    )


def downgrade() -> None:
    op.execute(f"UPDATE project SET name = '{ANCIEN}' WHERE name = '{NOUVEAU}'")
