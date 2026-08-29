from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from parrot_gateway.domain.models import BuiltRequest, IRChatRequest, IRChatResponse


class ProviderAdaptor(ABC):
    """Protocol translation only; transport is handled by ProviderExecutor."""

    name: str

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    @abstractmethod
    def get_endpoint(self, request: IRChatRequest) -> str: ...

    @abstractmethod
    def build_request(self, request: IRChatRequest) -> BuiltRequest: ...

    @abstractmethod
    async def parse_response(
        self, upstream_resp: httpx.Response, raw_body: bytes
    ) -> IRChatResponse: ...

    @abstractmethod
    async def parse_stream(self, response: httpx.Response) -> AsyncIterator[bytes]: ...
