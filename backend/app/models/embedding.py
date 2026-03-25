"""Document embedding model — pgvector for semantic search."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # article, ...
    source_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(20), index=True)  # For finance articles

    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(1536))  # OpenAI text-embedding-3-small dimension

    model: Mapped[str] = mapped_column(String(100), default="unknown")
    token_count: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_doc_embeddings_source", "source_type", "source_id"),
        # HNSW index created via raw SQL in migration (needs operator class)
    )
