from __future__ import annotations

from collections.abc import AsyncIterator

from parrot_gateway.domain.models import IRChatRequest, IRChatResponse
from parrot_gateway.infrastructure.provider_executor import ProviderExecutor
from parrot_gateway.services.model_router import ModelRouter


class ChatCompletionService:
    """Application orchestration for OpenAI-compatible chat completions."""

    def __init__(self, router: ModelRouter, executor: ProviderExecutor) -> None:
        self._router = router
        self._executor = executor

    async def complete(self, request: IRChatRequest) -> IRChatResponse:
        adaptor = self._router.resolve(request.model)
        return await self._executor.complete(adaptor, request)

    async def stream(self, request: IRChatRequest) -> AsyncIterator[bytes]:
        adaptor = self._router.resolve(request.model)
        async for chunk in self._executor.stream(adaptor, request):
            yield chunk
