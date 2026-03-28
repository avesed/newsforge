"""Add translation fields for Chinese translation of titles and full text.

Revision ID: 016_add_translation_fields
Revises: 015_merge_events_into_stories
Create Date: 2026-03-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "016_add_translation_fields"
down_revision: Union[str, None] = "015_merge_events_into_stories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # asyncpg requires exactly ONE SQL statement per op.execute()
    op.execute("ALTER TABLE articles ADD COLUMN title_zh VARCHAR(500)")
    op.execute("ALTER TABLE articles ADD COLUMN full_text_zh TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS full_text_zh")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS title_zh")
