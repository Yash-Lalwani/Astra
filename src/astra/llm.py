from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel

from astra.config import settings

Role = Literal["strong", "fast"]

_rate_limiter = InMemoryRateLimiter(requests_per_second=settings.llm_requests_per_second)


def _chat_model(role: Role, temperature: float = 0.0) -> ChatOpenAI:
    """A ChatOpenAI client pointed at OpenRouter."""
    # require_parameters: only use providers that support every parameter we send.
    # order + only: try these providers in this order and never use any other.
    routing: dict[str, Any] = {"require_parameters": True}
    if settings.openrouter_provider_list:
        routing |= {
            "order": settings.openrouter_provider_list,
            "only": settings.openrouter_provider_list,
        }
    return ChatOpenAI(
        model=settings.strong_model if role == "strong" else settings.fast_model,
        temperature=temperature,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        extra_body={"provider": routing},
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        rate_limiter=_rate_limiter,
    )


def plain_model(role: Role, temperature: float = 0.0) -> Runnable:
    return _chat_model(role, temperature)


def tool_model(role: Role, tools: Sequence[Any]) -> Runnable:
    return _chat_model(role).bind_tools(tools)


def structured_model(role: Role, schema: type[BaseModel]) -> Runnable:
    """Returns {"raw": AIMessage, "parsed": schema | None, "parsing_error": ...}; the raw
    message is kept so its token usage can be counted."""
    return _chat_model(role).with_structured_output(
        schema, method=settings.structured_output_method, include_raw=True
    )


def embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        dimensions=settings.embedding_dims,
        api_key=settings.openai_api_key,
    )


def usage_of(message: AIMessage) -> tuple[int, int]:
    """(input_tokens, output_tokens) from the message's usage_metadata; (0, 0) when absent."""
    usage = message.usage_metadata
    if not usage:
        return 0, 0
    return usage["input_tokens"], usage["output_tokens"]
