"""events.scope: 'kommune' (default) or 'distrikt' for district-wide notices (M1 step 2).

A district-wide notice («Oslo politidistrikt» in the municipality field) is stored with
scope 'distrikt', kommunenummer NULL and no point, and is never geocoded (spec §8.3,
decided 2026-11-13).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE events ADD COLUMN scope TEXT NOT NULL DEFAULT 'kommune' "
        "CHECK (scope IN ('kommune','distrikt'))"
    )
    op.execute(
        "CREATE INDEX events_distrikt_idx ON events (district, first_message_at DESC) "
        "WHERE scope = 'distrikt'"
    )


def downgrade() -> None:
    # Notices can't exist without the column: drop them first (they are public data, re-ingested on upgrade
    # only while still in the Politiloggen window).
    op.execute("DELETE FROM events WHERE scope = 'distrikt'")
    op.execute("DROP INDEX events_distrikt_idx")
    op.execute("ALTER TABLE events DROP COLUMN scope")
