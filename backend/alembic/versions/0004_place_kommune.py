"""places.kommunenummer (M1 step 5, D9).

The municipality the place's centre lies in, from Kartverket's reverse point lookup. NULL when the
point is in no municipality (at sea, abroad). Places outside the ingested fylker are allowed; the
API flags them as not covered (spec §6, decided 2026-11-13).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE places ADD COLUMN kommunenummer TEXT")
    op.execute("CREATE INDEX places_device_idx ON places (device_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX places_device_idx")
    op.execute("ALTER TABLE places DROP COLUMN kommunenummer")
