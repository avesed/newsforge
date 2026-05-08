"""Shared test fixtures for NewsForge backend tests.

Uses the real PostgreSQL database (docker compose postgres service).
Each test gets a fresh engine+connection+transaction, rolled back for isolation.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.database import get_db
from app.main import create_app
from app.models.api_consumer import ApiConsumer

TEST_DB_URL = "postgresql+asyncpg://newsforge:newsforge@localhost:5432/newsforge"
TEST_API_KEY_RAW = "test-key-for-ml-batch-fixed"
TEST_API_KEY_HASH = hashlib.sha256(TEST_API_KEY_RAW.encode()).hexdigest()


@pytest.fixture()
async def db_session():
    """Fresh engine+connection+transaction per test, rolled back for isolation."""
    engine = create_async_engine(TEST_DB_URL, echo=False, pool_size=5)
    async with engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        await txn.rollback()
    await engine.dispose()


@pytest.fixture()
async def test_consumer(db_session: AsyncSession):
    """Insert a test API consumer for authentication."""
    consumer = ApiConsumer(
        id=uuid.uuid4(),
        name=f"test-ml-consumer-{uuid.uuid4().hex[:8]}",
        api_key=TEST_API_KEY_HASH,
        api_key_prefix=TEST_API_KEY_RAW[:8],
        is_active=True,
        rate_limit=1000,
    )
    db_session.add(consumer)
    await db_session.flush()
    return consumer


@pytest.fixture()
async def client(db_session: AsyncSession, test_consumer):
    """Async HTTP client wired to the test database session.

    Overrides get_db to use a nested transaction (SAVEPOINT) per request
    so that the endpoint's commit() only releases the savepoint.
    """
    app = create_app()

    async def _override_get_db():
        nested = await db_session.begin_nested()
        try:
            yield db_session
            await nested.commit()
        except Exception:
            await nested.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture()
def api_headers():
    """Headers with the test API key."""
    return {"X-API-Key": TEST_API_KEY_RAW}
