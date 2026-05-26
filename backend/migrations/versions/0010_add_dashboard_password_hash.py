"""Add dashboard_password_hash to vehicles.

Revision ID: 0010
Revises: 9d2c4a5e8f01
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "9d2c4a5e8f01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("dashboard_password_hash", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "dashboard_password_hash")
