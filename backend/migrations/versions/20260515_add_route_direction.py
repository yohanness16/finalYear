"""add route direction

Revision ID: 9d2c4a5e8f01
Revises: 20251010000001
Create Date: 2026-05-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d2c4a5e8f01"
down_revision: str | Sequence[str] | None = "20251010000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "routes",
        sa.Column("direction", sa.String(length=10), server_default="forward", nullable=False),
    )
    op.drop_index(op.f("ix_routes_route_number"), table_name="routes")
    op.create_index(op.f("ix_routes_route_number"), "routes", ["route_number"], unique=False)
    op.create_unique_constraint(
        "uq_route_number_direction",
        "routes",
        ["route_number", "direction"],
    )
    op.alter_column("routes", "direction", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_route_number_direction", "routes", type_="unique")
    op.drop_index(op.f("ix_routes_route_number"), table_name="routes")
    op.create_index(op.f("ix_routes_route_number"), "routes", ["route_number"], unique=True)
    op.drop_column("routes", "direction")
