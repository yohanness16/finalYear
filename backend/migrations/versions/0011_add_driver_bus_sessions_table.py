"""add driver_bus_sessions table

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-11 00:14:15.962338

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "driver_bus_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), nullable=False, index=True),
        sa.Column("login_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("logout_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="active", server_default="active"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("driver_bus_sessions")
