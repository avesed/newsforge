"""System-level key/value settings table.

Holds process-level secrets and runtime config that should survive container
restart but don't warrant dedicated tables. First consumer: auto-bootstrapped
JWT signing secret (env takes priority; if unset, we generate one and persist
it here on first startup).

Revision ID: 020_system_settings
Revises: 019_extend_external_id
Create Date: 2026-04-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "020_system_settings"
down_revision: Union[str, None] = "019_extend_external_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS system_settings ("
        "key VARCHAR(128) PRIMARY KEY, "
        "value TEXT NOT NULL, "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_settings")
