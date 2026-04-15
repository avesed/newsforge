"""LLM Gateway -- database-driven provider configuration.

Resolution priority:
1. DB providers (is_enabled=True, is_default=True or highest priority)
2. Environment variables (fallback for bootstrap/no-DB scenarios)

Provider config cached in Redis (60s TTL) to avoid DB queries on every LLM call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.llm.types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    StreamEvent,
    TokenUsage,
)

logger = logging.getLogger(__name__)

_gateway: LLMGateway | None = None
PROVIDER_CACHE_KEY = "llm_providers"
PROVIDER_CACHE_TTL = 60  # seconds
AGENT_CONFIG_CACHE_KEY = "agent_llm_configs"
AGENT_CONFIG_CACHE_TTL = 60  # seconds


class LLMGateway:
    """Singleton LLM gateway with database-driven provider resolution."""

    # In-memory cache TTL (seconds). Keeps hot data in-process but
    # ensures cross-process invalidation converges within this window.
    _MEM_CACHE_TTL = 10

    def __init__(self):
        self._clients: dict[str, AsyncOpenAI] = {}  # provider_name -> client
        self._client_keys: dict[str, str] = {}  # provider_name -> cache_key for change detection
        self._providers: list[dict] | None = None  # In-memory provider cache
        self._providers_ts: float = 0  # When _providers was last populated
        self._agent_configs: dict[str, dict] | None = None  # In-memory agent config cache
        self._agent_configs_ts: float = 0  # When _agent_configs was last populated
        self._env_client: AsyncOpenAI | None = None  # Fallback env client

    async def _load_providers(self) -> list[dict]:
        """Load provider configs from Redis cache or DB."""
        # 0. In-memory cache (with TTL to handle cross-process invalidation)
        if self._providers is not None and (time.monotonic() - self._providers_ts) < self._MEM_CACHE_TTL:
            return self._providers
        self._providers = None

        # 1. Try Redis cache
        try:
            from app.services.cache_service import cache

            cached = await cache.get(PROVIDER_CACHE_KEY)
            if cached:
                self._providers = cached
                self._providers_ts = time.monotonic()
                return cached
        except Exception:
            logger.debug("Redis cache unavailable for provider lookup")

        # 2. Query DB
        try:
            from sqlalchemy import select

            from app.db.database import get_session_factory
            from app.models.llm_provider import LLMProvider

            factory = get_session_factory()
            async with factory() as db:
                result = await db.execute(
                    select(LLMProvider)
                    .where(LLMProvider.is_enabled == True)  # noqa: E712
                    .order_by(
                        LLMProvider.is_default.desc(),
                        LLMProvider.priority.desc(),
                    )
                )
                providers = result.scalars().all()

                if providers:
                    provider_dicts = [
                        {
                            "name": p.name,
                            "provider_type": p.provider_type,
                            "api_key": p.api_key,
                            "api_base": p.api_base,
                            "default_model": p.default_model,
                            "embedding_model": p.embedding_model,
                            "purpose_models": p.purpose_models or {},
                            "extra_params": p.extra_params or {},
                            "is_default": p.is_default,
                            "priority": p.priority,
                        }
                        for p in providers
                    ]
                    # Cache in Redis
                    try:
                        from app.services.cache_service import cache

                        await cache.set(
                            PROVIDER_CACHE_KEY,
                            provider_dicts,
                            PROVIDER_CACHE_TTL,
                        )
                    except Exception:
                        logger.warning("Failed to cache LLM providers in Redis", exc_info=True)

                    logger.info(
                        "Loaded %d LLM provider(s) from DB: %s",
                        len(provider_dicts),
                        ", ".join(p["name"] for p in provider_dicts),
                    )
                    self._providers = provider_dicts
                    self._providers_ts = time.monotonic()
                    return provider_dicts
                else:
                    logger.warning("No enabled LLM providers found in database")

        except Exception:
            logger.exception("Failed to load LLM providers from DB")

        return []

    async def _load_agent_configs(self) -> dict[str, dict]:
        """Load agent LLM configs from Redis cache or DB.

        Returns: {agent_id: {provider: {...}|None, model: str|None, profile: {...}|None}}
        """
        # 0. In-memory cache (with TTL to handle cross-process invalidation)
        if self._agent_configs is not None and (time.monotonic() - self._agent_configs_ts) < self._MEM_CACHE_TTL:
            return self._agent_configs
        self._agent_configs = None

        # 1. Try Redis cache
        try:
            from app.services.cache_service import cache

            cached = await cache.get(AGENT_CONFIG_CACHE_KEY)
            if cached:
                logger.debug("Agent config cache hit (Redis): %d configs", len(cached))
                self._agent_configs = cached
                self._agent_configs_ts = time.monotonic()
                return cached
        except Exception:
            logger.debug("Redis cache unavailable for agent config lookup")

        # 2. Query DB
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import joinedload

            from app.db.database import get_session_factory
            from app.models.agent_llm_config import AgentLLMConfig

            factory = get_session_factory()
            async with factory() as db:
                result = await db.execute(
                    select(AgentLLMConfig)
                    .options(
                        joinedload(AgentLLMConfig.provider),
                        joinedload(AgentLLMConfig.profile),
                    )
                )
                configs = result.scalars().unique().all()

                if configs:
                    config_dict: dict[str, dict] = {}
                    for c in configs:
                        provider_data = None
                        if c.provider and c.provider.is_enabled:
                            provider_data = {
                                "name": c.provider.name,
                                "provider_type": c.provider.provider_type,
                                "api_key": c.provider.api_key,
                                "api_base": c.provider.api_base,
                                "default_model": c.provider.default_model,
                                "embedding_model": c.provider.embedding_model,
                                "purpose_models": c.provider.purpose_models or {},
                                "extra_params": c.provider.extra_params or {},
                                "is_default": c.provider.is_default,
                                "priority": c.provider.priority,
                            }

                        profile_data = None
                        if c.profile:
                            profile_data = {
                                "temperature": c.profile.temperature,
                                "max_tokens": c.profile.max_tokens,
                                "top_p": c.profile.top_p,
                                "thinking_enabled": c.profile.thinking_enabled,
                                "thinking_budget_tokens": c.profile.thinking_budget_tokens,
                                "timeout_seconds": c.profile.timeout_seconds,
                                "max_retries": c.profile.max_retries,
                                "extra_params": c.profile.extra_params or {},
                            }

                        config_dict[c.agent_id] = {
                            "provider": provider_data,
                            "model": c.model,
                            "profile": profile_data,
                        }

                    # Cache in Redis
                    try:
                        from app.services.cache_service import cache

                        await cache.set(
                            AGENT_CONFIG_CACHE_KEY,
                            config_dict,
                            AGENT_CONFIG_CACHE_TTL,
                        )
                    except Exception:
                        logger.warning("Failed to cache agent configs in Redis", exc_info=True)

                    logger.info(
                        "Loaded %d agent LLM config(s) from DB: %s",
                        len(config_dict),
                        ", ".join(config_dict.keys()),
                    )
                    self._agent_configs = config_dict
                    self._agent_configs_ts = time.monotonic()
                    return config_dict

        except Exception:
            logger.exception("Failed to load agent LLM configs from DB")

        return {}

    async def _get_provider_config(
        self, purpose: str | None = None
    ) -> tuple[AsyncOpenAI, str, str | None, dict, dict | None]:
        """Get the appropriate client + model for a purpose.

        Returns: (client, model, embedding_model, extra_params, profile_dict | None)
        """
        # --- Agent config lookup (takes highest priority) ---
        agent_configs = await self._load_agent_configs()
        profile: dict | None = None

        if purpose and purpose in agent_configs:
            agent_cfg = agent_configs[purpose]
            profile = agent_cfg.get("profile")
            agent_provider = agent_cfg.get("provider")
            agent_model = agent_cfg.get("model")

            if agent_provider:
                # Agent has a dedicated provider with full connection info
                client = self._get_client(agent_provider)
                model = agent_model or agent_provider["default_model"]
                extra_params = agent_provider.get("extra_params") or {}
                logger.debug(
                    "Agent config resolved: purpose=%s provider=%s model=%s profile=%s",
                    purpose, agent_provider["name"], model,
                    bool(profile),
                )
                return client, model, agent_provider.get("embedding_model"), extra_params, profile

            if agent_model:
                # Agent has only a model override — use it with the default provider
                providers = await self._load_providers()
                if providers:
                    provider = providers[0]
                    client = self._get_client(provider)
                    extra_params = provider.get("extra_params") or {}
                    logger.debug(
                        "Agent config model override: purpose=%s model=%s profile=%s",
                        purpose, agent_model, bool(profile),
                    )
                    return client, agent_model, provider.get("embedding_model"), extra_params, profile

            # Agent config exists but only has a profile (or provider is disabled)
            # — fall through to normal resolution, profile will be returned at the end
            if not agent_provider and not agent_model and profile:
                logger.debug(
                    "Agent config profile-only: purpose=%s, falling through to default provider",
                    purpose,
                )

        # --- Standard provider resolution ---
        providers = await self._load_providers()

        if providers:
            # Find provider for this purpose
            provider = None
            model = None

            # First: check if any provider has a specific purpose mapping
            if purpose:
                for p in providers:
                    if purpose in (p.get("purpose_models") or {}):
                        provider = p
                        model = p["purpose_models"][purpose]
                        break

            # Second: use default provider (already sorted by is_default desc, priority desc)
            if not provider:
                provider = providers[0]
                model = provider["default_model"]

            # Get or create client for this provider
            client = self._get_client(provider)
            extra_params = provider.get("extra_params") or {}
            return client, model, provider.get("embedding_model"), extra_params, profile

        # Fallback: env vars
        logger.warning("No DB providers available, falling back to env vars")
        client, model, embed_model = self._get_env_client()
        return client, model, embed_model, {}, profile

    def _get_client(self, provider: dict) -> AsyncOpenAI:
        """Get or create an AsyncOpenAI client for a provider.

        Recreates the client if api_key or api_base changed (e.g. admin updated provider).
        """
        name = provider["name"]
        cache_key = f"{name}:{provider['api_key'][:8]}:{provider['api_base']}"
        if name not in self._clients or self._client_keys.get(name) != cache_key:
            self._clients[name] = AsyncOpenAI(
                api_key=provider["api_key"],
                base_url=provider["api_base"],
                timeout=120.0,
            )
            self._client_keys[name] = cache_key
        return self._clients[name]

    def _get_env_client(self) -> tuple[AsyncOpenAI, str, str | None]:
        """Fallback to environment variable config."""
        if not self._env_client:
            from app.core.config import get_settings

            settings = get_settings()
            self._env_client = AsyncOpenAI(
                api_key=settings.openai_api_key or "not-configured",
                base_url=settings.openai_api_base,
                timeout=120.0,
            )
        from app.core.config import get_settings

        settings = get_settings()
        return self._env_client, settings.openai_model, "text-embedding-3-small"

    @staticmethod
    def _apply_profile(
        request: ChatRequest,
        extra_params: dict,
        profile: dict | None,
        purpose: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply profile defaults to build kwargs and extra_body.

        Priority: request explicit values > profile > provider extra_params > model defaults.

        Returns: (param_overrides, extra_body)
            param_overrides contains temperature, max_tokens, top_p as applicable.
            extra_body contains merged extra_params with profile/thinking config.
        """
        param_overrides: dict[str, Any] = {}

        # --- temperature ---
        temperature = request.temperature
        if temperature is None and profile and profile.get("temperature") is not None:
            temperature = profile["temperature"]
        if temperature is not None:
            param_overrides["temperature"] = temperature

        # --- max_tokens ---
        max_tokens = request.max_tokens
        if max_tokens is None and profile and profile.get("max_tokens") is not None:
            max_tokens = profile["max_tokens"]
        if max_tokens is not None:
            param_overrides["max_tokens"] = max_tokens

        # --- top_p (profile only, no request-level field) ---
        if profile and profile.get("top_p") is not None:
            param_overrides["top_p"] = profile["top_p"]

        # --- extra_body: provider base -> profile extras -> thinking config ---
        extra_body: dict[str, Any] = dict(extra_params) if extra_params else {}

        if profile:
            # Merge profile extra_params on top of provider extras
            profile_extras = profile.get("extra_params") or {}
            if profile_extras:
                extra_body = {**extra_body, **profile_extras}

            # Thinking config -> chat_template_kwargs
            thinking_enabled = profile.get("thinking_enabled")
            thinking_budget = profile.get("thinking_budget_tokens")
            if thinking_enabled is not None or thinking_budget is not None:
                chat_tpl = dict(extra_body.get("chat_template_kwargs", {}))
                if thinking_enabled is not None:
                    chat_tpl["enable_thinking"] = thinking_enabled
                # Only send thinking_budget_tokens when thinking is enabled
                if thinking_budget is not None and thinking_enabled is not False:
                    chat_tpl["thinking_budget_tokens"] = thinking_budget
                extra_body["chat_template_kwargs"] = chat_tpl

            logger.debug(
                "Applied LLM profile for purpose=%s: overrides=%s extra_body_keys=%s",
                purpose,
                {k: v for k, v in param_overrides.items()},
                list(extra_body.keys()) if extra_body else [],
            )

        return param_overrides, extra_body

    async def chat(
        self, request: ChatRequest, purpose: str | None = None
    ) -> ChatResponse:
        """Send a chat completion request."""
        client, default_model, _, extra_params, profile = await self._get_provider_config(purpose)
        model = request.model or default_model

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
        }

        # Apply profile + request overrides
        param_overrides, extra_body = self._apply_profile(
            request, extra_params, profile, purpose,
        )
        kwargs.update(param_overrides)

        if request.response_format:
            kwargs["response_format"] = request.response_format
        if request.tools:
            kwargs["tools"] = request.tools
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice

        if extra_body:
            kwargs["extra_body"] = extra_body
            logger.debug("Applying extra_body: %s", list(extra_body.keys()))

        logger.info(
            "LLM request: model=%s purpose=%s tokens_limit=%s temp=%s profile=%s",
            model, purpose, kwargs.get("max_tokens"), kwargs.get("temperature"),
            bool(profile),
        )

        # Determine timeout and retry from profile
        req_timeout: float | None = None
        if profile and profile.get("timeout_seconds"):
            req_timeout = float(profile["timeout_seconds"])

        max_retries = 0
        if profile and profile.get("max_retries"):
            max_retries = profile["max_retries"]

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                if req_timeout is not None:
                    # Use streaming internally so the LLM server (e.g. vLLM)
                    # can detect client disconnect and abort generation on
                    # timeout, freeing GPU resources.  Non-streaming requests
                    # don't allow the server to detect disconnect until it
                    # tries to send the completed response.
                    chat_resp = await self._streaming_chat_with_timeout(
                        client, kwargs, req_timeout, model, purpose,
                    )
                else:
                    chat_resp = await self._non_streaming_chat(
                        client, kwargs, model, purpose,
                    )
                # success — break out of retry loop
                return chat_resp
            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError(
                    f"LLM request timed out after {req_timeout}s "
                    f"(purpose={purpose}, model={model})"
                )
                logger.warning(
                    "LLM request timeout (stream aborted): model=%s purpose=%s "
                    "timeout=%.0fs attempt=%d/%d",
                    model, purpose, req_timeout, attempt + 1, max_retries + 1,
                )
                if attempt < max_retries:
                    continue
                raise last_error
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        "LLM request failed, retrying: model=%s purpose=%s "
                        "attempt=%d/%d error=%s",
                        model, purpose, attempt + 1, max_retries + 1,
                        str(e)[:200],
                    )
                    continue
                logger.exception(
                    "LLM chat request failed (model=%s, purpose=%s, attempts=%d)",
                    model, purpose, attempt + 1,
                )
                raise
        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise RuntimeError("Unreachable: retry loop exited without result or error")

    async def _non_streaming_chat(
        self,
        client: AsyncOpenAI,
        kwargs: dict[str, Any],
        model: str,
        purpose: str | None,
    ) -> ChatResponse:
        """Standard non-streaming chat completion."""
        response = await client.chat.completions.create(**kwargs)
        return self._parse_chat_response(response, model, purpose)

    async def _streaming_chat_with_timeout(
        self,
        client: AsyncOpenAI,
        kwargs: dict[str, Any],
        timeout: float,
        model: str,
        purpose: str | None,
    ) -> ChatResponse:
        """Chat using streaming internally, with timeout that aborts server-side.

        When asyncio.wait_for cancels the task on timeout, the stream
        connection is closed.  The LLM server (e.g. vLLM) detects the
        disconnect between streaming chunks and aborts generation,
        freeing GPU resources immediately.
        """
        stream_kwargs = {**kwargs, "stream": True}

        # Debug: log actual params being sent to API
        logger.info(
            "LLM streaming request params: purpose=%s temperature=%s top_p=%s "
            "max_tokens=%s extra_body=%s all_keys=%s",
            purpose,
            stream_kwargs.get("temperature"),
            stream_kwargs.get("top_p"),
            stream_kwargs.get("max_tokens"),
            stream_kwargs.get("extra_body"),
            [k for k in stream_kwargs.keys() if k != "messages"],
        )

        async def _collect() -> ChatResponse:
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            resp_model = model
            finish_reason = "stop"
            usage_data = None

            stream = await client.chat.completions.create(**stream_kwargs)
            try:
                async for chunk in stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            content_parts.append(delta.content)
                        # Reasoning models (Qwen3, DeepSeek-R1)
                        r = getattr(delta, "reasoning", None) or getattr(
                            delta, "reasoning_content", None
                        )
                        if r:
                            reasoning_parts.append(r)
                        if chunk.choices[0].finish_reason:
                            finish_reason = chunk.choices[0].finish_reason
                    if chunk.model:
                        resp_model = chunk.model
                    if chunk.usage:
                        usage_data = chunk.usage
            finally:
                await stream.close()

            content = "".join(content_parts)
            reasoning = "".join(reasoning_parts)

            # Handle empty content with reasoning (same as non-streaming)
            if not content and reasoning:
                logger.warning(
                    "LLM streaming response content empty but reasoning present "
                    "(model=%s, purpose=%s, finish=%s, reasoning_len=%d)",
                    resp_model, purpose, finish_reason, len(reasoning),
                )
                content = _extract_json_from_reasoning(reasoning)
            elif not content:
                logger.warning(
                    "LLM streaming response content empty "
                    "(model=%s, purpose=%s, finish=%s)",
                    resp_model, purpose, finish_reason,
                )

            total_tokens = usage_data.total_tokens if usage_data else 0
            logger.info(
                "LLM response (streamed): model=%s purpose=%s tokens=%d "
                "finish=%s content_len=%d",
                resp_model, purpose, total_tokens, finish_reason, len(content),
            )

            return ChatResponse(
                content=content,
                model=resp_model,
                usage=TokenUsage(
                    prompt_tokens=usage_data.prompt_tokens if usage_data else 0,
                    completion_tokens=(
                        usage_data.completion_tokens if usage_data else 0
                    ),
                    total_tokens=total_tokens,
                    cached_tokens=(
                        getattr(
                            getattr(usage_data, "prompt_tokens_details", None),
                            "cached_tokens", 0,
                        ) or 0
                        if usage_data
                        else 0
                    ),
                ),
                tool_calls=None,  # Pipeline agents don't use tool_calls
                finish_reason=finish_reason or "stop",
            )

        return await asyncio.wait_for(_collect(), timeout=timeout)

    @staticmethod
    def _parse_chat_response(
        response: Any, model: str, purpose: str | None
    ) -> ChatResponse:
        """Parse a non-streaming chat completion response into ChatResponse."""
        choice = response.choices[0]
        msg = choice.message
        usage = response.usage

        # Extract content — handle reasoning models (Qwen3, DeepSeek-R1)
        content = msg.content or ""
        if not content:
            reasoning = getattr(msg, "reasoning", None) or getattr(
                msg, "reasoning_content", None
            )
            if reasoning:
                logger.warning(
                    "LLM response content is empty but reasoning is present "
                    "(model=%s, purpose=%s, finish_reason=%s, reasoning_len=%d). "
                    "The model may have exhausted tokens during thinking. "
                    "Consider increasing max_tokens or adding "
                    '{"chat_template_kwargs": {"enable_thinking": false}} '
                    "to the provider's extra_params.",
                    model, purpose, choice.finish_reason, len(reasoning),
                )
                content = _extract_json_from_reasoning(reasoning)
            else:
                logger.warning(
                    "LLM response content is empty (model=%s, purpose=%s, "
                    "finish_reason=%s)",
                    model, purpose, choice.finish_reason,
                )

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        total_tokens = usage.total_tokens if usage else 0
        logger.info(
            "LLM response: model=%s purpose=%s tokens=%d finish=%s content_len=%d",
            response.model, purpose, total_tokens,
            choice.finish_reason, len(content),
        )

        return ChatResponse(
            content=content,
            model=response.model,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=total_tokens,
                cached_tokens=(
                    getattr(
                        getattr(usage, "prompt_tokens_details", None),
                        "cached_tokens", 0,
                    ) or 0
                    if usage
                    else 0
                ),
            ),
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )

    async def chat_stream(
        self, request: ChatRequest, purpose: str | None = None
    ) -> AsyncGenerator[StreamEvent, None]:
        """Send a streaming chat completion request."""
        client, default_model, _, extra_params, profile = await self._get_provider_config(purpose)
        model = request.model or default_model

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        # Apply profile + request overrides
        param_overrides, extra_body = self._apply_profile(
            request, extra_params, profile, purpose,
        )
        kwargs.update(param_overrides)

        if request.response_format:
            kwargs["response_format"] = request.response_format

        if extra_body:
            kwargs["extra_body"] = extra_body

        logger.info(
            "LLM stream request: model=%s purpose=%s profile=%s",
            model, purpose, bool(profile),
        )

        if profile and profile.get("timeout_seconds"):
            kwargs["timeout"] = float(profile["timeout_seconds"])

        try:
            stream = await client.chat.completions.create(**kwargs)

            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield StreamEvent(type="content_delta", data=delta.content)

                if chunk.usage:
                    yield StreamEvent(
                        type="usage",
                        data=TokenUsage(
                            prompt_tokens=chunk.usage.prompt_tokens,
                            completion_tokens=chunk.usage.completion_tokens,
                            total_tokens=chunk.usage.total_tokens,
                        ),
                    )

            yield StreamEvent(type="finish")
        except Exception:
            logger.exception(
                "LLM stream request failed (model=%s, purpose=%s)", model, purpose
            )
            raise

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        """Generate embeddings for texts."""
        client, _, embed_model, extra_params, _ = await self._get_provider_config("embedding")
        model = request.model or embed_model or "text-embedding-3-small"

        logger.info("Embedding request: model=%s texts=%d", model, len(request.texts))

        try:
            kwargs: dict[str, Any] = {"model": model, "input": request.texts}
            if request.dimensions is not None:
                kwargs["dimensions"] = request.dimensions

            response = await client.embeddings.create(**kwargs)

            embeddings = [item.embedding for item in response.data]
            usage = response.usage

            return EmbedResponse(
                embeddings=embeddings,
                model=response.model,
                usage=TokenUsage(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                ),
            )
        except Exception:
            logger.exception("Embedding request failed (model=%s)", model)
            raise

    async def is_configured(self) -> bool:
        """Check if any LLM provider is configured (DB or env)."""
        providers = await self._load_providers()
        if providers:
            return True
        from app.core.config import get_settings

        return bool(get_settings().openai_api_key)

    async def test_connection(
        self, provider_config: dict
    ) -> tuple[bool, str]:
        """Test a provider connection with a simple request."""
        try:
            extra_params = provider_config.get("extra_params") or {}
            client = AsyncOpenAI(
                api_key=provider_config["api_key"],
                base_url=provider_config["api_base"],
                timeout=15.0,
            )
            kwargs: dict[str, Any] = {
                "model": provider_config["default_model"],
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
            }
            if extra_params:
                kwargs["extra_body"] = extra_params

            response = await client.chat.completions.create(**kwargs)
            return True, f"OK (model: {response.model})"
        except Exception as e:
            return False, str(e)[:200]


def _extract_json_from_reasoning(reasoning: str) -> str:
    """Try to extract a JSON object/array from reasoning text.

    Reasoning models sometimes include their intended JSON output within the
    thinking trace. We look for the last complete JSON block.
    Returns the extracted JSON string, or empty string if none found.
    """
    import re

    # Look for ```json ... ``` blocks first
    json_blocks = re.findall(r"```json\s*([\s\S]*?)```", reasoning)
    if json_blocks:
        return json_blocks[-1].strip()

    # Look for last { ... } or [ ... ] block that parses as JSON
    for match in reversed(list(re.finditer(r"(\{[\s\S]*\}|\[[\s\S]*\])", reasoning))):
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            continue

    return ""


def get_llm_gateway() -> LLMGateway:
    """Get or create the LLM gateway singleton."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


def reset_llm_gateway() -> None:
    """Reset the gateway (e.g., after config change or provider update)."""
    global _gateway
    _gateway = None


async def invalidate_agent_config_cache() -> None:
    """Invalidate the agent LLM config cache (Redis + in-memory).

    Call after any mutation to agent_llm_configs or llm_profiles tables.
    """
    try:
        from app.services.cache_service import cache

        await cache.invalidate(AGENT_CONFIG_CACHE_KEY)
    except Exception:
        logger.debug("Failed to invalidate agent config Redis cache")

    # Also clear the in-memory cache on the gateway singleton
    if _gateway is not None:
        _gateway._agent_configs = None
