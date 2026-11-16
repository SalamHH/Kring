"""places.place_name (M1 step 9).

The name of the search result the place was made from, such as «Tøyen skole» or «Hølandsgata 1A»,
shown on the Hjem card («Tøyen skole · 1 km · hverdager 08-16») and in the edit screen. The label
(«Skolen») stays the user's own name for the place. NULL for places made before this migration.
Decided 2026-11-15, spec §8.4.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE places ADD COLUMN place_name TEXT "
        "CONSTRAINT places_place_name_len CHECK (char_length(place_name) BETWEEN 1 AND 100)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE places DROP COLUMN place_name")
