"""Extend external_id from VARCHAR(255) to VARCHAR(512).

Google News RSS article IDs (base64-encoded) frequently exceed 255 chars,
causing INSERT failures.

Revision ID: 019_extend_external_id
Revises: 018_add_source_name
Create Date: 2026-04-14
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_extend_external_id"
down_revision: Union[str, None] = "018_add_source_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE articles ALTER COLUMN external_id TYPE VARCHAR(512)")


def downgrade() -> None:
    op.execute("ALTER TABLE articles ALTER COLUMN external_id TYPE VARCHAR(255)")
