"""Admin LLM provider, profile, and agent config management."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.auth import require_admin
from app.core.llm.gateway import (
    PROVIDER_CACHE_KEY,
    get_llm_gateway,
    invalidate_agent_config_cache,
    reset_llm_gateway,
)
from app.db.database import get_db
from app.models.agent_llm_config import AgentLLMConfig
from app.models.llm_profile import LLMProfile
from app.models.llm_provider import LLMProvider
from app.models.user import User
from app.pipeline.agents.registry import get_agent_registry
from app.schemas.base import CamelModel
from app.services.cache_service import cache

router = APIRouter(prefix="/admin/llm", tags=["admin"])


# --- Schemas ---


class ProviderResponse(CamelModel):
    id: uuid.UUID
    name: str
    provider_type: str
    api_base: str
    default_model: str
    embedding_model: str | None = None
    purpose_models: dict | None = None
    extra_params: dict | None = None
    is_enabled: bool
    is_default: bool
    priority: int
    created_at: datetime | None = None
    api_key_masked: str = ""


class ProviderCreateRequest(CamelModel):
    name: str
    provider_type: str  # openai, anthropic, custom
    api_key: str
    api_base: str = "https://api.openai.com/v1"
    default_model: str = "gpt-4o-mini"
    embedding_model: str | None = None
    purpose_models: dict | None = None
    extra_params: dict | None = None


class ProviderUpdateRequest(CamelModel):
    name: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    default_model: str | None = None
    embedding_model: str | None = None
    purpose_models: dict | None = None
    extra_params: dict | None = None
    is_enabled: bool | None = None
    priority: int | None = None


class TestConnectionRequest(CamelModel):
    api_key: str
    api_base: str = "https://api.openai.com/v1"
    default_model: str = "gpt-4o-mini"
    extra_params: dict | None = None


class TestConnectionResponse(CamelModel):
    success: bool
    message: str


# --- Helpers ---


def _mask_api_key(key: str) -> str:
    """Mask API key, showing first 3 and last 4 chars."""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}...{key[-4:]}"


def _to_response(provider: LLMProvider) -> ProviderResponse:
    """Convert ORM model to response schema."""
    return ProviderResponse(
        id=provider.id,
        name=provider.name,
        provider_type=provider.provider_type,
        api_base=provider.api_base,
        default_model=provider.default_model,
        embedding_model=provider.embedding_model,
        purpose_models=provider.purpose_models,
        extra_params=provider.extra_params,
        is_enabled=provider.is_enabled,
        is_default=provider.is_default,
        priority=provider.priority,
        created_at=provider.created_at,
        api_key_masked=_mask_api_key(provider.api_key),
    )


async def _invalidate_provider_cache() -> None:
    """Invalidate Redis cache and reset gateway singleton."""
    await cache.invalidate(PROVIDER_CACHE_KEY)
    reset_llm_gateway()


# --- Endpoints ---


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all LLM providers."""
    result = await db.execute(
        select(LLMProvider).order_by(
            LLMProvider.is_default.desc(),
            LLMProvider.priority.desc(),
            LLMProvider.name,
        )
    )
    providers = result.scalars().all()
    return [_to_response(p) for p in providers]


@router.post(
    "/providers",
    response_model=ProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    request: ProviderCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new LLM provider."""
    # Check name uniqueness
    existing = await db.execute(
        select(LLMProvider).where(LLMProvider.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider with name '{request.name}' already exists",
        )

    provider = LLMProvider(
        name=request.name,
        provider_type=request.provider_type,
        api_key=request.api_key,
        api_base=request.api_base,
        default_model=request.default_model,
        embedding_model=request.embedding_model,
        purpose_models=request.purpose_models,
        extra_params=request.extra_params,
    )
    db.add(provider)
    await db.flush()

    await _invalidate_provider_cache()
    return _to_response(provider)


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: uuid.UUID,
    request: ProviderUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an LLM provider."""
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )

    # Apply partial update — use by_alias=False to get snake_case field names
    # matching the SQLAlchemy model columns (CamelModel defaults to camelCase)
    update_data = request.model_dump(exclude_unset=True, by_alias=False)
    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.flush()
    await _invalidate_provider_cache()
    await invalidate_agent_config_cache()
    return _to_response(provider)


@router.delete(
    "/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_provider(
    provider_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an LLM provider."""
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )

    await db.delete(provider)
    await db.flush()
    await _invalidate_provider_cache()
    await invalidate_agent_config_cache()


@router.post(
    "/providers/{provider_id}/test", response_model=TestConnectionResponse
)
async def test_provider_connection(
    provider_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Test connection to an existing provider."""
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )

    gateway = get_llm_gateway()
    success, message = await gateway.test_connection(
        {
            "api_key": provider.api_key,
            "api_base": provider.api_base,
            "default_model": provider.default_model,
            "extra_params": provider.extra_params,
        }
    )
    return TestConnectionResponse(success=success, message=message)


@router.post("/providers/test", response_model=TestConnectionResponse)
async def test_connection_unsaved(
    request: TestConnectionRequest,
    admin: User = Depends(require_admin),
):
    """Test connection without saving (for the 'add provider' form)."""
    gateway = get_llm_gateway()
    success, message = await gateway.test_connection(
        {
            "api_key": request.api_key,
            "api_base": request.api_base,
            "default_model": request.default_model,
            "extra_params": request.extra_params,
        }
    )
    return TestConnectionResponse(success=success, message=message)


@router.put(
    "/providers/{provider_id}/default", response_model=ProviderResponse
)
async def set_default_provider(
    provider_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set a provider as the default. Unsets all others."""
    result = await db.execute(
        select(LLMProvider).where(LLMProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )

    # Unset all defaults
    await db.execute(
        update(LLMProvider).values(is_default=False)
    )

    # Set the target as default
    provider.is_default = True
    await db.flush()

    await _invalidate_provider_cache()
    await invalidate_agent_config_cache()
    return _to_response(provider)


# =====================================================================
# Profile Schemas
# =====================================================================


class ProfileResponse(CamelModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    thinking_enabled: bool | None = None
    thinking_budget_tokens: int | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    extra_params: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileCreateRequest(CamelModel):
    name: str
    description: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    thinking_enabled: bool | None = None
    thinking_budget_tokens: int | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    extra_params: dict | None = None


class ProfileUpdateRequest(CamelModel):
    name: str | None = None
    description: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    thinking_enabled: bool | None = None
    thinking_budget_tokens: int | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    extra_params: dict | None = None


# =====================================================================
# Agent Config Schemas
# =====================================================================


class AgentConfigResponse(CamelModel):
    id: uuid.UUID
    agent_id: str
    provider_id: uuid.UUID | None = None
    provider_name: str | None = None  # Denormalized for display
    model: str | None = None
    profile_id: uuid.UUID | None = None
    profile_name: str | None = None  # Denormalized for display
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentConfigUpsertRequest(CamelModel):
    provider_id: uuid.UUID | None = None
    model: str | None = None
    profile_id: uuid.UUID | None = None


class AgentConfigListResponse(CamelModel):
    configs: list[AgentConfigResponse]
    registered_agents: list[str]  # All agent_ids from registry


# =====================================================================
# Profile Helpers
# =====================================================================


def _validate_profile_params(data: dict) -> None:
    """Validate profile parameter ranges. Raises HTTPException(422) on invalid values."""
    temp = data.get("temperature")
    if temp is not None and not (0 <= temp <= 2):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="temperature must be between 0 and 2",
        )
    top_p = data.get("top_p")
    if top_p is not None and not (0 <= top_p <= 1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="top_p must be between 0 and 1",
        )
    max_tokens = data.get("max_tokens")
    if max_tokens is not None and max_tokens <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_tokens must be greater than 0",
        )
    thinking_budget = data.get("thinking_budget_tokens")
    if thinking_budget is not None and thinking_budget <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="thinking_budget_tokens must be greater than 0",
        )
    timeout = data.get("timeout_seconds")
    if timeout is not None and timeout <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeout_seconds must be greater than 0",
        )
    retries = data.get("max_retries")
    if retries is not None and (retries < 0 or retries > 10):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_retries must be between 0 and 10",
        )


def _to_profile_response(profile: LLMProfile) -> ProfileResponse:
    """Convert ORM model to response schema."""
    return ProfileResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        top_p=profile.top_p,
        thinking_enabled=profile.thinking_enabled,
        thinking_budget_tokens=profile.thinking_budget_tokens,
        timeout_seconds=profile.timeout_seconds,
        max_retries=profile.max_retries,
        extra_params=profile.extra_params,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _to_agent_config_response(config: AgentLLMConfig) -> AgentConfigResponse:
    """Convert ORM model to response schema with denormalized names."""
    return AgentConfigResponse(
        id=config.id,
        agent_id=config.agent_id,
        provider_id=config.provider_id,
        provider_name=config.provider.name if config.provider else None,
        model=config.model,
        profile_id=config.profile_id,
        profile_name=config.profile.name if config.profile else None,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# =====================================================================
# Profile Endpoints
# =====================================================================


@router.get("/profiles", response_model=list[ProfileResponse])
async def list_profiles(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all LLM profiles."""
    result = await db.execute(
        select(LLMProfile).order_by(LLMProfile.name)
    )
    profiles = result.scalars().all()
    return [_to_profile_response(p) for p in profiles]


@router.post(
    "/profiles",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(
    request: ProfileCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new LLM profile."""
    existing = await db.execute(
        select(LLMProfile).where(LLMProfile.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Profile with name '{request.name}' already exists",
        )

    _validate_profile_params(request.model_dump(exclude_unset=True, by_alias=False))

    profile = LLMProfile(
        name=request.name,
        description=request.description,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        top_p=request.top_p,
        thinking_enabled=request.thinking_enabled,
        thinking_budget_tokens=request.thinking_budget_tokens,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
        extra_params=request.extra_params,
    )
    db.add(profile)
    await db.flush()

    logger.info("Admin %s created LLM profile: %s", admin.email, profile.name)
    await invalidate_agent_config_cache()
    return _to_profile_response(profile)


@router.patch("/profiles/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: uuid.UUID,
    request: ProfileUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an LLM profile."""
    result = await db.execute(
        select(LLMProfile).where(LLMProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )

    update_data = request.model_dump(exclude_unset=True, by_alias=False)
    _validate_profile_params(update_data)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.flush()
    await db.refresh(profile)
    logger.info("Admin %s updated LLM profile: %s", admin.email, profile.name)
    await invalidate_agent_config_cache()
    return _to_profile_response(profile)


@router.delete(
    "/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_profile(
    profile_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an LLM profile."""
    result = await db.execute(
        select(LLMProfile).where(LLMProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )

    profile_name = profile.name
    await db.delete(profile)
    await db.flush()
    logger.info("Admin %s deleted LLM profile: %s", admin.email, profile_name)
    await invalidate_agent_config_cache()


# =====================================================================
# Agent Config Endpoints
# =====================================================================


@router.get("/agents", response_model=AgentConfigListResponse)
async def list_agent_configs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all agent LLM configs with denormalized names.

    Also returns all registered agent_ids so the frontend knows which
    agents exist even if they have no custom config.
    """
    result = await db.execute(
        select(AgentLLMConfig)
        .options(joinedload(AgentLLMConfig.provider), joinedload(AgentLLMConfig.profile))
        .order_by(AgentLLMConfig.agent_id)
    )
    configs = result.unique().scalars().all()

    registry = get_agent_registry()
    # Include non-registry pipeline purposes (classifier, cleaner) plus the
    # story pipeline purposes (story_matcher, story_refresher, story_merger)
    # so admins can route them to dedicated providers/profiles too.
    registered_agents = sorted(
        list(registry.all_agents().keys())
        + ["classifier", "cleaner", "story_matcher", "story_refresher", "story_merger"]
    )

    return AgentConfigListResponse(
        configs=[_to_agent_config_response(c) for c in configs],
        registered_agents=registered_agents,
    )


@router.put("/agents/{agent_id}", response_model=AgentConfigResponse)
async def upsert_agent_config(
    agent_id: str,
    request: AgentConfigUpsertRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update an agent's LLM configuration."""
    # Validate provider_id exists if provided
    if request.provider_id is not None:
        provider_result = await db.execute(
            select(LLMProvider).where(LLMProvider.id == request.provider_id)
        )
        if not provider_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider not found",
            )

    # Validate profile_id exists if provided
    if request.profile_id is not None:
        profile_result = await db.execute(
            select(LLMProfile).where(LLMProfile.id == request.profile_id)
        )
        if not profile_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found",
            )

    # Upsert: find existing or create new
    result = await db.execute(
        select(AgentLLMConfig).where(AgentLLMConfig.agent_id == agent_id)
    )
    config = result.scalar_one_or_none()

    if config:
        # Update existing
        config.provider_id = request.provider_id
        config.model = request.model
        config.profile_id = request.profile_id
    else:
        # Create new
        config = AgentLLMConfig(
            agent_id=agent_id,
            provider_id=request.provider_id,
            model=request.model,
            profile_id=request.profile_id,
        )
        db.add(config)

    await db.flush()
    # Re-query with joinedload to get relationships (refresh doesn't work in async)
    refreshed = await db.execute(
        select(AgentLLMConfig)
        .options(joinedload(AgentLLMConfig.provider), joinedload(AgentLLMConfig.profile))
        .where(AgentLLMConfig.agent_id == agent_id)
    )
    config = refreshed.unique().scalars().one()

    logger.info("Admin %s upserted agent config: %s", admin.email, agent_id)
    await invalidate_agent_config_cache()
    return _to_agent_config_response(config)


@router.delete(
    "/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_agent_config(
    agent_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an agent's LLM config (restore to defaults)."""
    result = await db.execute(
        select(AgentLLMConfig).where(AgentLLMConfig.agent_id == agent_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent config not found",
        )

    await db.delete(config)
    await db.flush()
    logger.info("Admin %s deleted agent config: %s", admin.email, agent_id)
    await invalidate_agent_config_cache()
