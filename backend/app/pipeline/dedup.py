"""Dedup engine — URL normalization + SimHash content fingerprinting + language detection.

Three-layer dedup (before LLM classification to save cost):
1. URL normalization + exact match
2. Title SimHash (Hamming distance <= 3 within 24h window)
3. Content MinHash (Jaccard > 0.7, if full text available)

Language detection is applied after dedup check (only for non-duplicate articles).
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from lingua import Language, LanguageDetectorBuilder
from simhash import Simhash

logger = logging.getLogger(__name__)

# --- Language Detection (singleton) ---

_detector = (
    LanguageDetectorBuilder
    .from_all_languages()
    .with_minimum_relative_distance(0.25)
    .build()
)


def detect_language(text: str) -> str | None:
    """Detect the language of text using lingua.

    Returns ISO 639-1 code (e.g., "en", "zh", "ja") or None.
    """
    if not text or len(text.strip()) < 10:
        return None
    try:
        result = _detector.detect_language_of(text)
        if result:
            return result.iso_code_639_1.name.lower()
    except Exception:
        logger.debug("Language detection failed for text: %.50s...", text)
    return None

# URL params to strip for normalization
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
})


def normalize_url(url: str) -> str:
    """Normalize URL by removing tracking params and fragments."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=False)
    filtered = {k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS}
    clean_query = urlencode(filtered, doseq=True)
    normalized = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        parsed.params,
        clean_query,
        "",  # Remove fragment
    ))
    return normalized


def compute_simhash(text: str) -> str:
    """Compute SimHash fingerprint of text. Returns hex string."""
    # Tokenize: split on whitespace and CJK characters
    tokens = _tokenize(text.lower())
    if not tokens:
        return hashlib.md5(text.encode()).hexdigest()[:16]

    sh = Simhash(tokens)
    return format(sh.value, "016x")


def simhash_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two SimHash hex strings."""
    try:
        v1 = int(hash1, 16)
        v2 = int(hash2, 16)
        return bin(v1 ^ v2).count("1")
    except (ValueError, TypeError):
        return 64  # Max distance on error


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer for SimHash — splits on whitespace + CJK n-grams."""
    # Latin words
    words = re.findall(r"[a-z0-9]+", text)

    # CJK bigrams
    cjk_chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af\u3040-\u309f\u30a0-\u30ff]", text)
    for i in range(len(cjk_chars) - 1):
        words.append(cjk_chars[i] + cjk_chars[i + 1])

    return words


class DedupEngine:
    """Dedup engine with Redis-backed recent hash storage."""

    def __init__(self, redis_client, window_hours: int = 24, simhash_threshold: int = 3):
        self._redis = redis_client
        self._window_hours = window_hours
        self._simhash_threshold = simhash_threshold

    async def is_duplicate(self, url: str, title: str) -> tuple[bool, str, str | None]:
        """Check if article is duplicate.

        Returns (is_dup, normalized_url, detected_language).
        Language detection runs only for non-duplicate articles.
        """
        norm_url = normalize_url(url)

        # 1. URL exact match
        url_key = f"nf:dedup:url:{hashlib.md5(norm_url.encode()).hexdigest()}"
        if await self._redis.exists(url_key):
            return True, norm_url, None

        # 2. Title SimHash
        title_hash = compute_simhash(title)
        similar = await self._find_similar_title(title_hash)
        if similar:
            logger.info("Dedup: title similar to existing article (hash=%s)", title_hash)
            return True, norm_url, None

        # Mark as seen
        ttl = self._window_hours * 3600
        await self._redis.setex(url_key, ttl, "1")
        await self._store_title_hash(title_hash, ttl)

        # Detect language for non-duplicate articles
        detected_lang = detect_language(title)

        return False, norm_url, detected_lang

    async def is_url_seen(self, url: str) -> tuple[bool, str]:
        """Check only URL dedup (no title check). Returns (seen, normalized_url)."""
        norm_url = normalize_url(url)
        url_key = f"nf:dedup:url:{hashlib.md5(norm_url.encode()).hexdigest()}"
        seen = bool(await self._redis.exists(url_key))
        return seen, norm_url

    async def mark_url_seen(self, url: str) -> str:
        """Mark a URL as seen without dedup-checking. Returns normalized URL."""
        norm_url = normalize_url(url)
        url_key = f"nf:dedup:url:{hashlib.md5(norm_url.encode()).hexdigest()}"
        await self._redis.setex(url_key, self._window_hours * 3600, "1")
        return norm_url

    async def _find_similar_title(self, title_hash: str) -> bool:
        """Check if any recent title hash is within Hamming distance threshold."""
        # Use a Redis sorted set with timestamp scores
        recent_hashes = await self._redis.zrangebyscore(
            "nf:dedup:titles", "-inf", "+inf"
        )
        for stored_hash in recent_hashes:
            if simhash_distance(title_hash, stored_hash) <= self._simhash_threshold:
                return True
        return False

    async def _store_title_hash(self, title_hash: str, ttl: int) -> None:
        """Store title hash with expiry."""
        import time

        now = time.time()
        await self._redis.zadd("nf:dedup:titles", {title_hash: now})
        # Trim old entries
        cutoff = now - ttl
        await self._redis.zremrangebyscore("nf:dedup:titles", "-inf", cutoff)
