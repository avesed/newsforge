"""Admin import/export endpoints for data migration."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.db.redis import get_redis
from app.models.article import Article
from app.models.user import User
from app.pipeline.dedup import normalize_url
from app.pipeline.queue import enqueue_article
from app.schemas.base import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/articles", tags=["admin"])

# Maximum upload size: 100MB
MAX_UPLOAD_SIZE = 100 * 1024 * 1024
BATCH_SIZE = 50


class ImportResultResponse(CamelModel):
    total: int
    imported: int
    duplicates: int
    errors: int
    error_details: list[str] = []


@router.post("/import", response_model=ImportResultResponse)
async def import_articles(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Import articles from a WebStock export JSON file.

    Accepts the JSON export format produced by WebStock's
    GET /admin/integrations/export-news endpoint. Articles are
    deduplicated by normalized URL and enqueued for pipeline processing.
    """
    # Validate content type
    if file.content_type and file.content_type not in (
        "application/json",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Expected JSON.",
        )

    # Read and parse file
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)[:200]}",
        )

    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)}MB.",
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {str(e)[:200]}",
        )

    # Validate structure
    if not isinstance(data, dict) or "articles" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid format: expected JSON with 'articles' array.",
        )

    articles_raw = data["articles"]
    if not isinstance(articles_raw, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid format: 'articles' must be an array.",
        )

    total = len(articles_raw)
    imported = 0
    duplicates = 0
    errors = 0
    error_details: list[str] = []

    redis = await get_redis()

    # Process in batches
    for batch_start in range(0, total, BATCH_SIZE):
        batch = articles_raw[batch_start : batch_start + BATCH_SIZE]

        # --- (C) Batch dedup: collect all normalized URLs and query once ---
        batch_urls: dict[int, str] = {}  # idx -> normalized_url
        for i, raw_article in enumerate(batch):
            url = raw_article.get("url")
            if url:
                batch_urls[batch_start + i] = normalize_url(url)

        existing_urls: set[str] = set()
        if batch_urls:
            url_list = list(set(batch_urls.values()))
            result = await db.execute(
                select(Article.url).where(Article.url.in_(url_list))
            )
            existing_urls = {row[0] for row in result.all()}

        # Collect enqueue jobs -- will be sent AFTER successful commit
        enqueue_jobs: list[dict] = []

        for i, raw_article in enumerate(batch):
            idx = batch_start + i
            try:
                # Validate required fields
                url = raw_article.get("url")
                title = raw_article.get("title")

                if not url or not title:
                    errors += 1
                    if len(error_details) < 20:
                        error_details.append(
                            f"Article #{idx}: missing required field (url or title)"
                        )
                    continue

                # Normalize URL for dedup
                normalized = batch_urls.get(idx) or normalize_url(url)

                # Check against batch dedup result set
                if normalized in existing_urls:
                    duplicates += 1
                    continue

                # Parse published_at
                published_at = None
                if raw_article.get("published_at"):
                    try:
                        published_at = datetime.fromisoformat(
                            raw_article["published_at"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        published_at = None

                # Build finance_metadata from WebStock fields
                finance_metadata = None
                symbol = raw_article.get("symbol")
                market = raw_article.get("market")
                if symbol or market:
                    finance_metadata = {}
                    if symbol:
                        finance_metadata["symbols"] = [symbol]
                    if market:
                        finance_metadata["market"] = market.lower()

                # --- (B) SAVEPOINT isolation: one failure won't roll back the batch ---
                article_id = uuid.uuid4()
                article = Article(
                    id=article_id,
                    title=title,
                    url=normalized,
                    source_name=raw_article.get("source_name"),
                    summary=raw_article.get("summary"),
                    published_at=published_at,
                    language=raw_article.get("language"),
                    finance_metadata=finance_metadata,
                    content_status="pending",
                )

                try:
                    async with db.begin_nested():
                        db.add(article)
                        await db.flush()
                except Exception as e:
                    # Likely a unique constraint violation (concurrent import)
                    logger.debug(
                        "Flush failed for article #%d (%s): %s",
                        idx, url[:80], e,
                    )
                    duplicates += 1
                    continue

                # Mark URL as seen to prevent intra-batch duplicates
                existing_urls.add(normalized)

                # --- (A) Collect enqueue job, do NOT send to Redis yet ---
                enqueue_jobs.append({
                    "article_id": str(article_id),
                    "title": title,
                    "url": normalized,
                    "source": "webstock_import",
                })

                imported += 1

            except Exception as e:
                errors += 1
                if len(error_details) < 20:
                    error_details.append(
                        f"Article #{idx}: {str(e)[:100]}"
                    )
                logger.warning(
                    "Failed to import article #%d: %s", idx, str(e)[:200]
                )

        # Commit each batch
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            # Batch failed -- discard enqueue jobs, adjust counters
            batch_imported = len(enqueue_jobs)
            enqueue_jobs.clear()
            errors += batch_imported
            imported -= batch_imported
            if len(error_details) < 20:
                error_details.append(
                    f"Batch commit failed at offset {batch_start}: {str(e)[:100]}"
                )
            logger.error(
                "Batch commit failed at offset %d: %s",
                batch_start,
                str(e)[:200],
            )
            continue

        # --- (A) Enqueue AFTER successful commit to prevent ghost queue entries ---
        for job in enqueue_jobs:
            await enqueue_article(redis, job, priority="low")

    logger.info(
        "Import completed: total=%d imported=%d duplicates=%d errors=%d (by admin %s)",
        total,
        imported,
        duplicates,
        errors,
        admin.email if hasattr(admin, "email") else admin.id,
    )

    return ImportResultResponse(
        total=total,
        imported=imported,
        duplicates=duplicates,
        errors=errors,
        error_details=error_details,
    )
