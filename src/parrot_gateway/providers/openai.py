from __future__ import annotations

import httpx

from parrot_gateway.core.config import Settings
from parrot_gateway.domain.models import BuiltRequest, IRChatRequest, IRChatResponse
from parrot_gateway.providers.base import ProviderAdaptor


class OpenAIAdaptor(ProviderAdaptor):
    """Adapter for providers exposing the OpenAI Chat Completions protocol."""

    name = "openai"

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> OpenAIAdaptor:
        return cls(
            httpx.AsyncClient(
                base_url=(base_url or settings.upstream_base_url).rstrip("/") + "/",
                timeout=settings.request_timeout_seconds,
            ),
            api_key or "",
        )

    def get_endpoint(self, request: IRChatRequest) -> str:
        return "chat/completions"

    def build_request(self, request: IRChatRequest) -> BuiltRequest:
        return BuiltRequest(
            method="POST",
            url=self.get_endpoint(request),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body=request.model_dump_json(exclude_none=True, by_alias=True).encode("utf-8"),
        )

    async def parse_response(
        self, upstream_resp: httpx.Response, raw_body: bytes
    ) -> IRChatResponse:
        return IRChatResponse.model_validate_json(raw_body)

    async def parse_stream(self, response: httpx.Response):
        async for chunk in response.aiter_raw():
            yield chunk
