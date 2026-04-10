"""Add source_name column to articles table.

Revision ID: 018_add_source_name
Revises: 017_finance_meta_gin
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_add_source_name"
down_revision: Union[str, None] = "017_finance_meta_gin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS source_name VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS source_name")
