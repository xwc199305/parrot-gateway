from __future__ import annotations

from collections.abc import AsyncIterator

from parrot_gateway.domain.errors import ProviderError
from parrot_gateway.domain.models import IRChatRequest
from parrot_gateway.providers.base import ProviderAdaptor


class ModelRouter:
    """Dispatch requests to an adaptor using the model name prefix."""

    def __init__(self, adaptors: dict[str, ProviderAdaptor]) -> None:
        if not adaptors:
            raise ValueError("At least one model prefix adaptor is required")
        self._adaptors = adaptors

    def resolve(self, model: str) -> ProviderAdaptor:
        matches = [
            (prefix, adaptor)
            for prefix, adaptor in self._adaptors.items()
            if model.startswith(prefix)
        ]
        if not matches:
            supported = ", ".join(sorted(self._adaptors))
            raise ProviderError(
                400,
                {
                    "error": {
                        "message": (
                            f"Unsupported model '{model}'. Expected a model starting with: "
                            f"{supported}"
                        ),
                        "type": "invalid_request_error",
                        "param": "model",
                        "code": "unsupported_model",
                    }
                },
            )
        return max(matches, key=lambda item: len(item[0]))[1]

    async def complete(self, request: IRChatRequest) -> dict:
        return await self.resolve(request.model).complete(request)

    async def stream(self, request: IRChatRequest) -> AsyncIterator[bytes]:
        adaptor = self.resolve(request.model)
        async for chunk in adaptor.stream(request):
            yield chunk
