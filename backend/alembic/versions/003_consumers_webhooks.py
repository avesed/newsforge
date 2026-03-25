"""API consumers and webhooks tables.

Revision ID: 003_consumers_webhooks
Revises: 002_multi_category
Create Date: 2026-03-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_consumers_webhooks"
down_revision: Union[str, None] = "002_multi_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- api_consumers table ---
    op.create_table(
        "api_consumers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("api_key", sa.String(128), unique=True, nullable=False),
        sa.Column("api_key_prefix", sa.String(8), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("rate_limit", sa.Integer, server_default=sa.text("100")),
        sa.Column("allowed_endpoints", sa.dialects.postgresql.ARRAY(sa.String(200))),
        sa.Column("last_used_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_api_consumers_api_key", "api_consumers", ["api_key"])

    op.create_index("ix_api_consumers_is_active", "api_consumers", ["is_active"])

    # --- webhooks table ---
    op.create_table(
        "webhooks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("consumer_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("api_consumers.id", ondelete="CASCADE"), index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("events", sa.dialects.postgresql.ARRAY(sa.String(50)), nullable=False),
        sa.Column("filters", sa.dialects.postgresql.JSONB),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("consecutive_failures", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_triggered_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_webhooks_active_events", "webhooks", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_webhooks_active_events", table_name="webhooks")
    op.drop_table("webhooks")
    op.drop_index("ix_api_consumers_is_active", table_name="api_consumers")
    op.drop_index("ix_api_consumers_api_key", table_name="api_consumers")
    op.drop_table("api_consumers")
