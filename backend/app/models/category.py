"""Category model — LLM auto-classification + admin configuration."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50))
    color: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)

    # Pipeline configuration — controls processing depth for this category
    pipeline_config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Seed data for initial migration
SEED_CATEGORIES = [
    {"slug": "finance", "name_en": "Finance", "name_zh": "财经", "icon": "trending-up", "color": "#10b981", "sort_order": 0},
    {"slug": "tech", "name_en": "Technology", "name_zh": "科技", "icon": "cpu", "color": "#3b82f6", "sort_order": 1},
    {"slug": "politics", "name_en": "Politics", "name_zh": "政要", "icon": "landmark", "color": "#ef4444", "sort_order": 2},
    {"slug": "entertainment", "name_en": "Entertainment", "name_zh": "娱乐", "icon": "film", "color": "#f59e0b", "sort_order": 3},
    {"slug": "gaming", "name_en": "Gaming", "name_zh": "游戏", "icon": "gamepad-2", "color": "#8b5cf6", "sort_order": 4},
    {"slug": "sports", "name_en": "Sports", "name_zh": "体育", "icon": "trophy", "color": "#06b6d4", "sort_order": 5},
    {"slug": "world", "name_en": "World", "name_zh": "国际", "icon": "globe", "color": "#6366f1", "sort_order": 6},
    {"slug": "science", "name_en": "Science", "name_zh": "科学", "icon": "flask-conical", "color": "#14b8a6", "sort_order": 7},
    {"slug": "health", "name_en": "Health", "name_zh": "健康", "icon": "heart-pulse", "color": "#ec4899", "sort_order": 8},
    {"slug": "other", "name_en": "Other", "name_zh": "其他", "icon": "ellipsis", "color": "#6b7280", "sort_order": 9},
]
