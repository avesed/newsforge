"""NewsForge database models.

Import all models here so SQLAlchemy Base metadata is fully populated
before any session is created. This is critical for standalone processes
(consumer, scheduler) that don't import models via FastAPI routers.
"""

from app.models.article import Article  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.source import Source  # noqa: F401
from app.models.feed import Feed  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.bookmark import Bookmark  # noqa: F401
from app.models.subscription import Subscription  # noqa: F401
from app.models.reading_history import ReadingHistory  # noqa: F401
from app.models.embedding import DocumentEmbedding  # noqa: F401
from app.models.pipeline_event import PipelineEvent  # noqa: F401
from app.models.api_consumer import ApiConsumer  # noqa: F401
from app.models.webhook import Webhook  # noqa: F401
from app.models.news_event import NewsEvent, EventArticle  # noqa: F401
from app.models.news_story import NewsStory, StoryArticle  # noqa: F401
from app.models.llm_provider import LLMProvider  # noqa: F401
from app.models.llm_profile import LLMProfile  # noqa: F401
from app.models.agent_llm_config import AgentLLMConfig  # noqa: F401
