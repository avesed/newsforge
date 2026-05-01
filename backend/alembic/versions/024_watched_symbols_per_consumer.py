"""Unique constraint changed to (symbol, market, registered_by).

Multiple consumers can independently subscribe to the same ticker.
The poller uses SELECT DISTINCT (symbol, market) to avoid duplicate
StockPulse requests.

Revision ID: 024
Revises: 023
"""

from alembic import op


revision = "024_watched_symbols_per_consumer"
down_revision = "023_watched_symbols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE watched_symbols "
        "DROP CONSTRAINT uq_watched_symbols_symbol_market"
    )
    # Coalesce existing NULLs to '' so the unique constraint works
    # (PostgreSQL treats NULL ≠ NULL, so UNIQUE on nullable columns
    # allows duplicate rows).
    op.execute(
        "UPDATE watched_symbols SET market = '' WHERE market IS NULL"
    )
    op.execute(
        "UPDATE watched_symbols SET registered_by = '' WHERE registered_by IS NULL"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ALTER COLUMN market SET DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ALTER COLUMN market SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ALTER COLUMN registered_by SET DEFAULT ''"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ALTER COLUMN registered_by SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ADD CONSTRAINT uq_watched_symbols_sym_mkt_consumer "
        "UNIQUE (symbol, market, registered_by)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE watched_symbols "
        "DROP CONSTRAINT IF EXISTS uq_watched_symbols_sym_mkt_consumer"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ALTER COLUMN market DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ALTER COLUMN registered_by DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE watched_symbols "
        "ADD CONSTRAINT uq_watched_symbols_symbol_market "
        "UNIQUE (symbol, market)"
    )
