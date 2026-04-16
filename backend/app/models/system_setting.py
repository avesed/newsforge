"""System-level key/value settings.

Holds bootstrapped process-level values (see app.core.secrets) that must
survive container restart. The ORM model exists mainly so `alembic
--autogenerate` doesn't propose dropping the table — runtime code uses
raw SQL via ``text()`` to avoid introducing a session dependency into
bootstrap helpers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
