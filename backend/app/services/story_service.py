"""Story service — narrative-level event clustering across entities and categories.

Provides batch story matching support:
- get_articles_for_story_matching: fetch article data needed by BatchStoryMatcher
- find_candidate_stories: two-layer pre-filtering (tags/categories overlap + embedding sort)
- create_story / link_article_to_story: DB mutation helpers
- update_story_embedding: recompute story embedding from linked articles
- deactivate_stale_stories: housekeeping
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import get_session_factory
from app.models.article import Article
from app.models.news_story import NewsStory, StoryArticle

logger = logging.getLogger(__name__)

STORY_WINDOW_HOURS = 72  # Only match active stories updated within this window


# ---------------------------------------------------------------------------
# Batch story matching helpers
# ---------------------------------------------------------------------------


async def get_articles_for_story_matching(article_ids: list[str]) -> list[dict]:
    """Fetch article data needed for story matching from DB.

    Includes embedding from the document_embeddings table (chunk_index=0)
    if available.
    """
    if not article_ids:
        return []

    factory = get_session_factory()
    async with factory() as session:
        # Core article fields
        result = await session.execute(
            select(
                Article.id, Article.title, Article.ai_summary, Article.summary,
                Article.tags, Article.categories,
            ).where(Article.id.in_(article_ids))
        )
        rows = result.fetchall()

        if not rows:
            return []

        articles_by_id: dict[str, dict] = {}
        for row in rows:
            aid = str(row.id)
            articles_by_id[aid] = {
                "id": aid,
                "title": row.title,
                "ai_summary": row.ai_summary,
                "summary": row.summary,
                "tags": row.tags or [],
                "categories": row.categories or [],
                "embedding": None,
            }

        # Extract embeddings from document_embeddings table
        emb_result = await session.execute(
            text("""
                SELECT source_id, embedding::text
                FROM document_embeddings
                WHERE source_type = 'article'
                  AND source_id = ANY(:ids)
                  AND chunk_index = 0
            """),
            {"ids": list(articles_by_id.keys())},
        )
        for emb_row in emb_result.fetchall():
            sid = emb_row.source_id
            if sid in articles_by_id and emb_row.embedding is not None:
                try:
                    import json as _json
                    emb = _json.loads(emb_row.embedding)
                    if isinstance(emb, list) and len(emb) > 0:
                        articles_by_id[sid]["embedding"] = emb
                except (ValueError, TypeError) as e:
                    logger.debug("Failed to parse embedding for article %s: %s", sid[:8], e)

    # Return in the same order as article_ids (where found)
    return [articles_by_id[aid] for aid in article_ids if aid in articles_by_id]


async def find_candidate_stories(
    article_tags: list[list[str]],
    article_categories: list[list[str]],
    article_embeddings: list[list[float] | None],
    limit: int = 30,
) -> list[dict]:
    """Two-layer candidate pre-filtering for story matching.

    Layer 1: tags/categories overlap with active stories
    Layer 2: embedding similarity sort (using mean of article embeddings)
    """
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STORY_WINDOW_HOURS)

    # Flatten all tags and categories from the batch
    batch_tags = list(set(t for tags in article_tags for t in tags if t))
    batch_categories = list(set(c for cats in article_categories for c in cats if c))

    async with factory() as session:
        # Layer 1: Find stories with overlapping key_entities (primary signal)
        # or BOTH same categories AND same story_type (secondary, stricter)
        candidates: list[dict] = []
        if batch_tags or batch_categories:
            overlap_query = text("""
                SELECT id, title, story_type, article_count, description
                FROM news_stories
                WHERE is_active = true
                  AND last_updated_at >= :cutoff
                  AND key_entities && :tags
                ORDER BY article_count DESC
                LIMIT :limit_val
            """)
            result = await session.execute(
                overlap_query,
                {
                    "cutoff": cutoff,
                    "tags": batch_tags[:50],
                    "limit_val": limit * 2,  # over-fetch for layer 2 filtering
                },
            )
            candidates = [dict(row._mapping) for row in result.fetchall()]

        # Layer 2: If we have embeddings, sort by cosine similarity
        valid_embeddings = [e for e in article_embeddings if e]
        if valid_embeddings and candidates:
            # Compute mean embedding of batch articles
            dim = len(valid_embeddings[0])
            mean_emb = [sum(e[i] for e in valid_embeddings) / len(valid_embeddings) for i in range(dim)]
            vec_str = "[" + ",".join(str(x) for x in mean_emb) + "]"

            candidate_ids = [str(c["id"]) for c in candidates]
            sort_query = text("""
                SELECT id, embedding <=> :vec AS distance
                FROM news_stories
                WHERE id = ANY(:ids)
                  AND embedding IS NOT NULL
                ORDER BY distance ASC
            """)
            result = await session.execute(
                sort_query,
                {"vec": vec_str, "ids": candidate_ids},
            )
            sorted_ids = [str(row.id) for row in result.fetchall()]

            # Re-order candidates by embedding distance
            id_order = {sid: i for i, sid in enumerate(sorted_ids)}
            candidates.sort(key=lambda c: id_order.get(str(c["id"]), 999))

        # If layer 1 returned too few, supplement with pure embedding search
        if len(candidates) < limit and valid_embeddings:
            dim = len(valid_embeddings[0])
            mean_emb = [sum(e[i] for e in valid_embeddings) / len(valid_embeddings) for i in range(dim)]
            vec_str = "[" + ",".join(str(x) for x in mean_emb) + "]"

            existing_ids = [str(c["id"]) for c in candidates]
            supplement_query = text("""
                SELECT id, title, story_type, article_count, description
                FROM news_stories
                WHERE is_active = true
                  AND last_updated_at >= :cutoff
                  AND embedding IS NOT NULL
                  AND id != ALL(:exclude_ids)
                ORDER BY embedding <=> :vec ASC
                LIMIT :limit_val
            """)
            result = await session.execute(
                supplement_query,
                {
                    "cutoff": cutoff,
                    "vec": vec_str,
                    "exclude_ids": existing_ids,
                    "limit_val": limit - len(candidates),
                },
            )
            candidates.extend(dict(row._mapping) for row in result.fetchall())

    return candidates[:limit]


async def update_story_embedding(story_id: str) -> None:
    """Update story embedding as mean of linked article embeddings."""
    factory = get_session_factory()

    async with factory() as session:
        try:
            # Get embeddings from pipeline_metadata of linked articles
            result = await session.execute(
                text("""
                    SELECT a.pipeline_metadata->'agents'->'embedder'->'data'->'embeddings'->0 AS embedding
                    FROM story_articles sa
                    JOIN articles a ON a.id = sa.article_id
                    WHERE sa.story_id = :story_id
                      AND a.pipeline_metadata->'agents'->'embedder'->'data'->'embeddings'->0 IS NOT NULL
                """),
                {"story_id": story_id},
            )
            rows = result.fetchall()

            if not rows:
                return

            # Compute mean embedding
            embeddings = []
            for row in rows:
                emb = row.embedding
                if isinstance(emb, str):
                    import json as _json
                    emb = _json.loads(emb)
                if isinstance(emb, list) and len(emb) > 0:
                    embeddings.append(emb)

            if not embeddings:
                return

            dim = len(embeddings[0])
            mean_emb = [sum(e[i] for e in embeddings) / len(embeddings) for i in range(dim)]
            vec_str = "[" + ",".join(str(x) for x in mean_emb) + "]"

            await session.execute(
                text("UPDATE news_stories SET embedding = :vec WHERE id = :sid"),
                {"vec": vec_str, "sid": story_id},
            )
            await session.commit()
            logger.debug("Updated story embedding: %s (%d articles)", story_id[:8], len(embeddings))
        except Exception:
            await session.rollback()
            logger.warning("Failed to update story embedding: %s", story_id[:8], exc_info=True)


async def create_story(
    title: str,
    description: str | None,
    story_type: str,
    key_entities: list[str] | None,
    categories: list[str] | None,
    embedding: list[float] | None,
    first_article_id: str,
) -> str:
    """Create a new story and link the first article. Returns story_id."""
    factory = get_session_factory()

    story_id = uuid.uuid4()
    async with factory() as session:
        try:
            story = NewsStory(
                id=story_id,
                title=title,
                description=description,
                story_type=story_type,
                status="developing",
                key_entities=key_entities,
                categories=categories,
                article_count=1,
                representative_article_id=first_article_id,
                is_active=True,
            )
            # Set embedding if available
            if embedding:
                story.embedding = embedding

            session.add(story)

            # Link first article
            sa = StoryArticle(
                story_id=story_id,
                article_id=first_article_id,
                matched_by="created",
                confidence=1.0,
            )
            session.add(sa)

            # Update article's story_id
            await session.execute(
                update(Article).where(Article.id == first_article_id).values(story_id=story_id)
            )

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to create story: '%s'", title[:50])
            raise

    logger.info("Created new story: '%s' (type=%s, id=%s)", title[:50], story_type, story_id)
    return str(story_id)


async def link_article_to_story(
    story_id: str,
    article_id: str,
    matched_by: str = "direct",
    confidence: float | None = None,
) -> None:
    """Link an article to an existing story."""
    factory = get_session_factory()

    async with factory() as session:
        # Upsert into story_articles (ignore if already linked)
        stmt = pg_insert(StoryArticle).values(
            story_id=story_id,
            article_id=article_id,
            matched_by=matched_by,
            confidence=confidence,
        ).on_conflict_do_nothing()
        result = await session.execute(stmt)

        # Only update count if a new row was actually inserted
        if result.rowcount > 0:
            await session.execute(
                update(NewsStory)
                .where(NewsStory.id == story_id)
                .values(
                    article_count=NewsStory.article_count + 1,
                    last_updated_at=func.now(),
                )
            )

            # Update article's story_id
            await session.execute(
                update(Article).where(Article.id == article_id).values(story_id=story_id)
            )

            await session.commit()
            logger.info("Linked article %s to story %s (by=%s)", article_id[:8], story_id[:8], matched_by)
        else:
            await session.commit()
            logger.debug("Article %s already linked to story %s, skipped", article_id[:8], story_id[:8])


async def deactivate_stale_stories(hours: int = 72) -> int:
    """Mark stories as concluded if not updated recently."""
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with factory() as session:
        result = await session.execute(
            update(NewsStory)
            .where(NewsStory.is_active == True, NewsStory.last_updated_at < cutoff)  # noqa: E712
            .values(is_active=False, status="concluded")
        )
        count = result.rowcount
        await session.commit()

    if count:
        logger.info("Deactivated %d stale stories (>%dh)", count, hours)
    return count


async def merge_similar_stories(similarity_threshold: float = 0.85) -> int:
    """Scheduled task: merge duplicate stories via multi-signal candidate finding + LLM.

    Three-layer candidate discovery (like story_matcher):
      Layer 1: Same story_type AND overlapping key_entities/categories
      Layer 2: Embedding cosine similarity (supplement, no hard cutoff)
    Deduplicated candidates are sent to LLM for final merge confirmation.

    Returns number of stories merged.
    """
    factory = get_session_factory()
    merged_count = 0

    async with factory() as session:
        # Layer 1: key_entities overlap (required), optionally same story_type
        # Note: categories overlap alone is too loose (e.g. "politics" matches unrelated stories)
        layer1_query = text("""
            SELECT DISTINCT
                LEAST(s1.id, s2.id) AS id1,
                GREATEST(s1.id, s2.id) AS id2
            FROM news_stories s1
            JOIN news_stories s2
              ON s1.id < s2.id
              AND s2.is_active = true
              AND s1.key_entities && s2.key_entities
            WHERE s1.is_active = true
              AND array_length(s1.key_entities, 1) > 0
            LIMIT 40
        """)
        layer1_result = await session.execute(layer1_query)
        layer1_pairs = {(str(r.id1), str(r.id2)) for r in layer1_result.fetchall()}

        # Layer 2: embedding similarity (top neighbors per story)
        layer2_query = text("""
            SELECT
                s1.id AS id1, s2.id AS id2
            FROM news_stories s1
            CROSS JOIN LATERAL (
                SELECT id, embedding
                FROM news_stories
                WHERE id > s1.id
                  AND is_active = true
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> s1.embedding ASC
                LIMIT 3
            ) s2
            WHERE s1.is_active = true
              AND s1.embedding IS NOT NULL
              AND (1 - (s1.embedding <=> s2.embedding)) > :threshold
        """)
        layer2_result = await session.execute(layer2_query, {"threshold": similarity_threshold})
        layer2_pairs = {(str(min(r.id1, r.id2)), str(max(r.id1, r.id2))) for r in layer2_result.fetchall()}

        # Union both layers
        all_pair_ids = layer1_pairs | layer2_pairs
        if not all_pair_ids:
            logger.debug("Story merger: no candidate pairs found")
            return 0

        logger.info(
            "Story merger candidates: %d from overlap, %d from embedding, %d total unique",
            len(layer1_pairs), len(layer2_pairs), len(all_pair_ids),
        )

        # Fetch story details for all candidates
        all_ids = list({sid for pair in all_pair_ids for sid in pair})
        detail_result = await session.execute(
            text("""
                SELECT id::text, title, article_count, story_type,
                       COALESCE(description, '') AS description,
                       key_entities, categories
                FROM news_stories
                WHERE id = ANY(:ids) AND is_active = true
            """),
            {"ids": [uuid.UUID(i) for i in all_ids]},
        )
        stories_by_id = {str(r.id): r for r in detail_result.fetchall()}

    # Build candidate pairs with details
    pairs = []
    for id1, id2 in all_pair_ids:
        s1, s2 = stories_by_id.get(id1), stories_by_id.get(id2)
        if not s1 or not s2:
            continue
        # Order by article_count desc (s1 = larger)
        if s1.article_count < s2.article_count:
            s1, s2 = s2, s1
        pairs.append((s1, s2))

    if not pairs:
        return 0

    # Build LLM prompt with richer context
    import json
    from app.core.llm.gateway import get_llm_gateway
    from app.core.llm.types import ChatMessage, ChatRequest

    pair_lines = []
    for i, (s1, s2) in enumerate(pairs, 1):
        desc1 = s1.description[:80] if s1.description else ""
        desc2 = s2.description[:80] if s2.description else ""
        entities1 = ", ".join((s1.key_entities or [])[:5])
        entities2 = ", ".join((s2.key_entities or [])[:5])
        pair_lines.append(
            f"{i}. A: \"{s1.title}\" ({s1.article_count}篇) [{s1.story_type}]\n"
            f"   描述：{desc1}\n"
            f"   实体：{entities1}\n"
            f"   B: \"{s2.title}\" ({s2.article_count}篇) [{s2.story_type}]\n"
            f"   描述：{desc2}\n"
            f"   实体：{entities2}"
        )

    prompt = (
        "以下故事线对可能描述同一事件，请判断哪些应该合并。\n\n"
        "合并规则：\n"
        "- 只有描述完全相同事件的故事线才应该合并\n"
        "- 仅因为涉及同一人物（如特朗普）但描述不同事件的，不应合并\n"
        "- 同一事件的不同角度（经济影响、军事行动、外交）可以合并\n"
        "- 不同事件即使主题相似（如两次不同的裁员）也不应合并\n\n"
        + "\n\n".join(pair_lines)
        + '\n\n请输出JSON格式：\n'
        '{"merge": [{"pair_index": 1, "reason": "简短理由"}], '
        '"skip": [{"pair_index": 2, "reason": "简短理由"}]}\n'
        "merge 表示应该合并（保留A），skip 表示不应合并。如果不确定，选择 skip。"
    )

    try:
        llm = get_llm_gateway()
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content="你是新闻事件分析专家，负责识别和合并重复的故事线。"),
                ChatMessage(role="user", content=prompt),
            ],
            response_format={"type": "json_object"},
        )
        response = await llm.chat(request, purpose="story_merger")
        data = json.loads(response.content)
    except Exception:
        logger.exception("Story merger LLM call failed")
        return 0

    # Execute confirmed merges
    # Track already-merged stories to avoid conflicts within same run
    merged_away: set[str] = set()

    for merge_item in data.get("merge", []):
        try:
            pair_idx = merge_item.get("pair_index", 0) - 1
            if pair_idx < 0 or pair_idx >= len(pairs):
                continue

            s1, s2 = pairs[pair_idx]
            keep_id, remove_id = str(s1.id), str(s2.id)

            # Skip if either story was already merged in this run
            if keep_id in merged_away or remove_id in merged_away:
                continue

            await _merge_stories(keep_id, remove_id)
            merged_away.add(remove_id)
            merged_count += 1
            logger.info(
                "Merged story '%s' into '%s' (%s)",
                s2.title[:40], s1.title[:40], merge_item.get("reason", ""),
            )
        except Exception:
            logger.warning("Failed to merge story pair %d", pair_idx + 1, exc_info=True)

    if merged_count:
        logger.info("Story merger: merged %d stories", merged_count)
    return merged_count


async def _merge_stories(keep_id: str, remove_id: str) -> None:
    """Merge remove_id story into keep_id story."""
    factory = get_session_factory()

    async with factory() as session:
        # Move all articles from remove to keep
        await session.execute(
            text("""
                UPDATE story_articles
                SET story_id = :keep_id
                WHERE story_id = :remove_id
                  AND article_id NOT IN (
                      SELECT article_id FROM story_articles WHERE story_id = :keep_id
                  )
            """),
            {"keep_id": keep_id, "remove_id": remove_id},
        )

        # Delete remaining duplicate links
        await session.execute(
            text("DELETE FROM story_articles WHERE story_id = :remove_id"),
            {"remove_id": remove_id},
        )

        # Update article.story_id references
        await session.execute(
            update(Article)
            .where(Article.story_id == remove_id)
            .values(story_id=keep_id)
        )

        # Update keep story's article count
        count_result = await session.execute(
            text("SELECT COUNT(*) FROM story_articles WHERE story_id = :sid"),
            {"sid": keep_id},
        )
        new_count = count_result.scalar() or 0

        await session.execute(
            update(NewsStory)
            .where(NewsStory.id == keep_id)
            .values(article_count=new_count, last_updated_at=func.now())
        )

        # Mark removed story as concluded
        await session.execute(
            update(NewsStory)
            .where(NewsStory.id == remove_id)
            .values(is_active=False, status="merged")
        )

        await session.commit()
