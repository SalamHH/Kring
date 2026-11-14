"""Push (M1 step 7; D7): events.ingested_at and events.notified_at.

- ingested_at: when the worker first stored the event, «detection» in §6.2 (D7). Filled by the
  database on insert (clock_timestamp(), not the transaction start). Events stored before this
  migration keep NULL: their detection time is unknown.
- notified_at: when the notifier has handled the event (pushed or decided not to). NULL means it
  still has to. Every event stored before this migration is marked handled, so deploying this
  never pushes old events.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added without a default first, so existing rows stay NULL (a volatile default would fill them).
    op.execute("ALTER TABLE events ADD COLUMN ingested_at TIMESTAMPTZ")
    op.execute("ALTER TABLE events ALTER COLUMN ingested_at SET DEFAULT clock_timestamp()")
    op.execute("ALTER TABLE events ADD COLUMN notified_at TIMESTAMPTZ")
    op.execute("UPDATE events SET notified_at = now()")
    op.execute("CREATE INDEX events_notify_pending_idx ON events (ingested_at) WHERE notified_at IS NULL")
    op.execute("CREATE INDEX notifications_receipt_idx ON notifications (sent_at) WHERE status = 'sent'")
    op.execute("CREATE INDEX notifications_place_sent_idx ON notifications (place_id, sent_at)")


def downgrade() -> None:
    op.execute("DROP INDEX notifications_place_sent_idx")
    op.execute("DROP INDEX notifications_receipt_idx")
    op.execute("DROP INDEX events_notify_pending_idx")
    op.execute("ALTER TABLE events DROP COLUMN notified_at")
    op.execute("ALTER TABLE events DROP COLUMN ingested_at")
