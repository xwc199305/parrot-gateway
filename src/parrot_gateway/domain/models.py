from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IRChatRequest(BaseModel):
    """OpenAI Chat Completions request accepted by the gateway."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    n: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    stop: str | list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[str, float] | None = None
    user: str | None = None
    modalities: list[str] | None = None
    audio: dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    reasoning_effort: str | None = None
    service_tier: str | None = None
    prediction: dict[str, Any] | None = None
    store: bool | None = None
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class BuiltRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


class IRChatResponse(BaseModel):
    """OpenAI Chat Completions response returned by adaptors."""

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, Any] | None = None
    service_tier: str | None = None
    system_fingerprint: str | None = None


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "parrot-gateway"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard] = Field(default_factory=list)
