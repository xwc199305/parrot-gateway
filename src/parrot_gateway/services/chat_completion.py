from __future__ import annotations

from collections.abc import AsyncIterator

from parrot_gateway.domain.models import IRChatRequest, IRChatResponse
from parrot_gateway.infrastructure.provider_executor import ProviderExecutor
from parrot_gateway.services.billing import BillingService
from parrot_gateway.services.model_router import ModelRouter


class ChatCompletionService:
    """Application orchestration for OpenAI-compatible chat completions."""

    def __init__(
        self, router: ModelRouter, executor: ProviderExecutor, billing: BillingService | None = None
    ) -> None:
        self._router = router
        self._executor = executor
        self._billing = billing

    async def complete(
        self, request: IRChatRequest, *, identity: object | None = None
    ) -> IRChatResponse:
        adaptor = self._router.resolve(request.model)
        record_id = await self._reserve(request, identity, adaptor.name)
        tenant_id = getattr(identity, "tenant_id", None)
        try:
            response = await self._executor.complete(adaptor, request)
        except Exception:
            if record_id and self._billing:
                await self._billing.finalize(record_id, failed=True, tenant_id=tenant_id)
            raise
        if record_id and self._billing:
            await self._billing.finalize(record_id, response, tenant_id=tenant_id)
        return response

    async def stream(
        self, request: IRChatRequest, *, identity: object | None = None
    ) -> AsyncIterator[bytes]:
        adaptor = self._router.resolve(request.model)
        record_id = await self._reserve(request, identity, adaptor.name)
        tenant_id = getattr(identity, "tenant_id", None)
        try:
            async for chunk in self._executor.stream(adaptor, request):
                yield chunk
        except Exception:
            if record_id and self._billing:
                await self._billing.finalize(record_id, failed=True, tenant_id=tenant_id)
            raise
        else:
            if record_id and self._billing:
                await self._billing.finalize(record_id, tenant_id=tenant_id)

    async def _reserve(
        self, request: IRChatRequest, identity: object | None, provider: str
    ) -> str | None:
        if not self._billing or not identity or not hasattr(identity, "tenant_id"):
            return None
        return await self._billing.reserve(
            request,
            identity.tenant_id,
            user_id=getattr(identity, "user_id", None),
            gateway_key_id=getattr(identity, "id", None),
            provider=provider,
        )
