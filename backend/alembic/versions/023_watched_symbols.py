"""watched_symbols table — drives StockPulse per-symbol polling.

Revision ID: 023
Revises: 022
"""

from alembic import op


revision = "023_watched_symbols"
down_revision = "022_story_refresh_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE watched_symbols (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(32) NOT NULL,
            market VARCHAR(8),
            registered_by VARCHAR(64),
            last_viewed_at TIMESTAMPTZ,
            last_polled_at TIMESTAMPTZ,
            last_error VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_watched_symbols_symbol_market UNIQUE (symbol, market)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_watched_symbols_symbol ON watched_symbols (symbol)"
    )
    op.execute(
        "CREATE INDEX ix_watched_symbols_registered_by "
        "ON watched_symbols (registered_by)"
    )
    op.execute(
        "CREATE INDEX ix_watched_symbols_last_viewed_at "
        "ON watched_symbols (last_viewed_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_watched_symbols_last_viewed_at")
    op.execute("DROP INDEX IF EXISTS ix_watched_symbols_registered_by")
    op.execute("DROP INDEX IF EXISTS ix_watched_symbols_symbol")
    op.execute("DROP TABLE IF EXISTS watched_symbols")
