"""Add timeout_seconds and max_retries to llm_profiles.

Revision ID: 011_profile_timeout_retry
Revises: 010_llm_profiles
Create Date: 2026-03-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_profile_timeout_retry"
down_revision: Union[str, None] = "010_llm_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_profiles", sa.Column("timeout_seconds", sa.Integer, nullable=True))
    op.add_column("llm_profiles", sa.Column("max_retries", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("llm_profiles", "max_retries")
    op.drop_column("llm_profiles", "timeout_seconds")
