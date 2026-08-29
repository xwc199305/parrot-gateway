"""Backward-compatible import for :mod:`parrot_gateway.domain.models`."""

from parrot_gateway.domain.models import (
    BuiltRequest,
    IRChatRequest,
    IRChatResponse,
    ModelCard,
    ModelList,
)

__all__ = [
    "BuiltRequest",
    "IRChatRequest",
    "IRChatResponse",
    "ModelCard",
    "ModelList",
]
