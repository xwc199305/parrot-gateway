from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from parrot_gateway.domain.errors import ProviderError
from parrot_gateway.domain.models import IRChatRequest, IRChatResponse
from parrot_gateway.providers.base import ProviderAdaptor


class ProviderExecutor:
    """Execute provider requests without knowing provider-specific protocols."""

    async def complete(self, adaptor: ProviderAdaptor, request: IRChatRequest) -> IRChatResponse:
        built = adaptor.build_request(request)
        try:
            response = await adaptor.client.request(
                built.method, built.url, headers=built.headers, content=built.body
            )
        except httpx.HTTPError as exc:
            raise ProviderError(502, {"message": "Upstream provider is unavailable"}) from exc
        if response.is_error:
            raise ProviderError(response.status_code, _error_body(response))
        return await adaptor.parse_response(response, response.content)

    async def stream(
        self, adaptor: ProviderAdaptor, request: IRChatRequest
    ) -> AsyncIterator[bytes]:
        built = adaptor.build_request(request)
        try:
            async with adaptor.client.stream(
                built.method, built.url, headers=built.headers, content=built.body
            ) as response:
                if response.is_error:
                    body = await response.aread()
                    raise ProviderError(response.status_code, _error_body_from_bytes(body))
                async for chunk in adaptor.parse_stream(response):
                    yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(502, {"message": "Upstream provider is unavailable"}) from exc


def _error_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"message": response.text}


def _error_body_from_bytes(body: bytes) -> Any:
    try:
        return httpx.Response(500, content=body).json()
    except ValueError:
        return {"message": body.decode("utf-8", errors="replace")}
