"""Convert all TIMESTAMP columns to TIMESTAMP WITH TIME ZONE.

Existing naive timestamps are interpreted as UTC during conversion.

Revision ID: 007_timestamptz
Revises: 006_llm_providers
"""

from alembic import op

revision = "007_timestamptz"
down_revision = "006_llm_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- articles ---
    op.execute("ALTER TABLE articles ALTER COLUMN published_at TYPE TIMESTAMPTZ USING published_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE articles ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE articles ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'")

    # --- sources ---
    op.execute("ALTER TABLE sources ALTER COLUMN last_fetched_at TYPE TIMESTAMPTZ USING last_fetched_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE sources ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE sources ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'")

    # --- feeds ---
    op.execute("ALTER TABLE feeds ALTER COLUMN last_polled_at TYPE TIMESTAMPTZ USING last_polled_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE feeds ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE feeds ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'")

    # --- users ---
    op.execute("ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'")

    # --- bookmarks ---
    op.execute("ALTER TABLE bookmarks ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")

    # --- subscriptions ---
    op.execute("ALTER TABLE subscriptions ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")

    # --- reading_history ---
    op.execute("ALTER TABLE reading_history ALTER COLUMN read_at TYPE TIMESTAMPTZ USING read_at AT TIME ZONE 'UTC'")

    # --- document_embeddings ---
    op.execute("ALTER TABLE document_embeddings ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")

    # --- pipeline_events ---
    op.execute("ALTER TABLE pipeline_events ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")

    # --- api_consumers ---
    op.execute("ALTER TABLE api_consumers ALTER COLUMN last_used_at TYPE TIMESTAMPTZ USING last_used_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE api_consumers ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE api_consumers ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'")

    # --- webhooks ---
    op.execute("ALTER TABLE webhooks ALTER COLUMN last_triggered_at TYPE TIMESTAMPTZ USING last_triggered_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE webhooks ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")

    # --- news_events ---
    op.execute("ALTER TABLE news_events ALTER COLUMN first_seen_at TYPE TIMESTAMPTZ USING first_seen_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE news_events ALTER COLUMN last_updated_at TYPE TIMESTAMPTZ USING last_updated_at AT TIME ZONE 'UTC'")

    # --- categories ---
    op.execute("ALTER TABLE categories ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")

    # --- llm_providers ---
    op.execute("ALTER TABLE llm_providers ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE llm_providers ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at AT TIME ZONE 'UTC'")


def downgrade() -> None:
    # --- articles ---
    op.execute("ALTER TABLE articles ALTER COLUMN published_at TYPE TIMESTAMP USING published_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE articles ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE articles ALTER COLUMN updated_at TYPE TIMESTAMP USING updated_at AT TIME ZONE 'UTC'")

    # --- sources ---
    op.execute("ALTER TABLE sources ALTER COLUMN last_fetched_at TYPE TIMESTAMP USING last_fetched_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE sources ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE sources ALTER COLUMN updated_at TYPE TIMESTAMP USING updated_at AT TIME ZONE 'UTC'")

    # --- feeds ---
    op.execute("ALTER TABLE feeds ALTER COLUMN last_polled_at TYPE TIMESTAMP USING last_polled_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE feeds ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE feeds ALTER COLUMN updated_at TYPE TIMESTAMP USING updated_at AT TIME ZONE 'UTC'")

    # --- users ---
    op.execute("ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE users ALTER COLUMN updated_at TYPE TIMESTAMP USING updated_at AT TIME ZONE 'UTC'")

    # --- bookmarks ---
    op.execute("ALTER TABLE bookmarks ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")

    # --- subscriptions ---
    op.execute("ALTER TABLE subscriptions ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")

    # --- reading_history ---
    op.execute("ALTER TABLE reading_history ALTER COLUMN read_at TYPE TIMESTAMP USING read_at AT TIME ZONE 'UTC'")

    # --- document_embeddings ---
    op.execute("ALTER TABLE document_embeddings ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")

    # --- pipeline_events ---
    op.execute("ALTER TABLE pipeline_events ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")

    # --- api_consumers ---
    op.execute("ALTER TABLE api_consumers ALTER COLUMN last_used_at TYPE TIMESTAMP USING last_used_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE api_consumers ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE api_consumers ALTER COLUMN updated_at TYPE TIMESTAMP USING updated_at AT TIME ZONE 'UTC'")

    # --- webhooks ---
    op.execute("ALTER TABLE webhooks ALTER COLUMN last_triggered_at TYPE TIMESTAMP USING last_triggered_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE webhooks ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")

    # --- news_events ---
    op.execute("ALTER TABLE news_events ALTER COLUMN first_seen_at TYPE TIMESTAMP USING first_seen_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE news_events ALTER COLUMN last_updated_at TYPE TIMESTAMP USING last_updated_at AT TIME ZONE 'UTC'")

    # --- categories ---
    op.execute("ALTER TABLE categories ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")

    # --- llm_providers ---
    op.execute("ALTER TABLE llm_providers ALTER COLUMN created_at TYPE TIMESTAMP USING created_at AT TIME ZONE 'UTC'")
    op.execute("ALTER TABLE llm_providers ALTER COLUMN updated_at TYPE TIMESTAMP USING updated_at AT TIME ZONE 'UTC'")
