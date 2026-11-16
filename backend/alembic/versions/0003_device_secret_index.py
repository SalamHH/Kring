"""Unique index on devices.secret_hash (M1 step 3).

Every authenticated request looks the device up by the SHA-256 of its bearer secret, so the
lookup needs an index. Unique, because two devices with the same secret would be the same caller.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX devices_secret_hash_key ON devices (secret_hash)")


def downgrade() -> None:
    op.execute("DROP INDEX devices_secret_hash_key")
