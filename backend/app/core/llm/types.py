"""LLM types — request/response models for the gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    model: str | None = None  # Override default model
    temperature: float | None = None  # None = use model default
    max_tokens: int | None = None  # None = use model default
    response_format: dict | None = None  # {"type": "json_object"}
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None


@dataclass
class ChatResponse:
    content: str
    model: str
    usage: TokenUsage
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class StreamEvent:
    """Tagged union for streaming events."""

    type: Literal["content_delta", "tool_call_delta", "usage", "finish"]
    data: Any = None


@dataclass
class EmbedRequest:
    texts: list[str]
    model: str | None = None
    dimensions: int | None = None


@dataclass
class EmbedResponse:
    embeddings: list[list[float]]
    model: str
    usage: TokenUsage


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider."""

    name: str  # openai, anthropic
    api_key: str
    api_base: str
    default_model: str
    models: dict[str, str] = field(default_factory=dict)  # purpose → model name
