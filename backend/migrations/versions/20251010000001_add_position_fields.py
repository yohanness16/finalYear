"""add position fields to vehicles

Revision ID: 20251010000001
Revises: 7fc9e171596d
Create Date: 2026-05-15 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20251010000001"
down_revision: Union[str, Sequence[str], None] = "7fc9e171596d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "last_lat" DOUBLE PRECISION')
    op.execute('ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "last_lon" DOUBLE PRECISION')
    op.execute('ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "speed" DOUBLE PRECISION')
    op.execute('ALTER TABLE "vehicles" ADD COLUMN IF NOT EXISTS "position_updated_at" TIMESTAMP WITH TIME ZONE')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "position_updated_at"')
    op.execute('ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "speed"')
    op.execute('ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "last_lon"')
    op.execute('ALTER TABLE "vehicles" DROP COLUMN IF EXISTS "last_lat"')