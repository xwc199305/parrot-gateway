from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from parrot_gateway.core.config import Settings
from parrot_gateway.domain.errors import BillingError, ProviderError
from parrot_gateway.domain.models import IRChatRequest, ModelList
from parrot_gateway.infrastructure.provider_executor import ProviderExecutor
from parrot_gateway.providers import (
    DeepseekAdaptor,
    KimiAdaptor,
    OpenAIAdaptor,
    QwenAdaptor,
)
from parrot_gateway.services.billing import BillingService
from parrot_gateway.services.chat_completion import ChatCompletionService
from parrot_gateway.services.gateway_auth import GatewayAuthService
from parrot_gateway.services.model_router import ModelRouter
from parrot_gateway.services.tokenizers import DeepseekTokenizer, KimiTokenizer, TokenizerRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    provider_keys: dict[str, str] = {}
    if settings.gateway_auth_mode == "database" and settings.database_url:
        from parrot_gateway.infrastructure.database import (
            SqlGatewayKeyRepository,
            create_session_factory,
        )

        credentials = SqlGatewayKeyRepository(create_session_factory(settings.database_url))
        for provider_name in ("openai", "deepseek", "kimi", "qwen"):
            key = await credentials.get_any_provider_key(provider_name)
            if key:
                provider_keys[provider_name] = key
    openai = OpenAIAdaptor.from_settings(
        settings,
        base_url=settings.openai_base_url,
        api_key=provider_keys.get("openai", ""),
    )
    deepseek = DeepseekAdaptor.from_settings(
        settings,
        base_url=settings.deepseek_base_url,
        api_key=provider_keys.get("deepseek", ""),
    )
    kimi = KimiAdaptor.from_settings(
        settings,
        base_url=settings.kimi_base_url,
        api_key=provider_keys.get("kimi", ""),
    )
    qwen = QwenAdaptor.from_settings(
        settings,
        base_url=settings.qwen_base_url,
        api_key=provider_keys.get("qwen", ""),
    )
    router = ModelRouter(
        {
            "deepseek-": deepseek,
            "kimi-": kimi,
            "moonshot-": kimi,
            "qwen-": qwen,
            "gpt-": openai,
            "o1-": openai,
            "o3-": openai,
            "chatgpt-": openai,
        }
    )
    billing = None
    tokenizer_registry = TokenizerRegistry()
    try:
        tokenizer_registry.register("deepseek", DeepseekTokenizer())
    except RuntimeError:
        pass
    if provider_keys.get("kimi"):
        tokenizer_registry.register("kimi", KimiTokenizer(provider_keys["kimi"]))
    if settings.gateway_auth_mode == "database" and settings.database_url:
        from parrot_gateway.infrastructure.database import create_session_factory

        billing = BillingService(create_session_factory(settings.database_url), tokenizer_registry)
    service = ChatCompletionService(router, ProviderExecutor(), billing)
    repository = None
    if settings.gateway_auth_mode == "database":
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required when GATEWAY_AUTH_MODE=database")
        from parrot_gateway.infrastructure.database import (
            SqlGatewayKeyRepository,
            create_session_factory,
        )

        repository = SqlGatewayKeyRepository(create_session_factory(settings.database_url))
    auth = GatewayAuthService(
        static_key=settings.gateway_api_key if settings.gateway_auth_mode == "static" else None,
        repository=repository,
        pepper=settings.gateway_key_pepper,
    )
    app.state.settings = settings
    app.state.service = service
    app.state.router = router
    app.state.auth = auth
    yield
    clients = {id(adaptor.client): adaptor.client for adaptor in (openai, deepseek, kimi, qwen)}
    for client in clients.values():
        await client.aclose()
    await tokenizer_registry.aclose()


app = FastAPI(title="Parrot Gateway", version="0.1.0", lifespan=lifespan)


def get_chat_service(request: Request) -> ChatCompletionService:
    return request.app.state.service


# Backward-compatible dependency name for integrations using the initial API.
get_provider = get_chat_service


async def verify_gateway_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    identity = await request.app.state.auth.authenticate(authorization)
    if identity is None and request.app.state.auth.enabled:
        raise HTTPException(status_code=401, detail={"message": "Invalid gateway API key"})
    request.state.gateway_identity = identity


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models", dependencies=[Depends(verify_gateway_key)])
async def list_models() -> ModelList:
    # Model discovery is provider-specific; add configured models here in phase two.
    return ModelList(data=[])


@app.post(
    "/v1/chat/completions",
    dependencies=[Depends(verify_gateway_key)],
    response_model=None,
)
async def create_chat_completion(
    request: Request,
    body: IRChatRequest,
    service: Annotated[ChatCompletionService, Depends(get_provider)],
) -> JSONResponse | StreamingResponse:
    try:
        if body.stream:
            return StreamingResponse(
                service.stream(body, identity=request.state.gateway_identity),
                media_type="text/event-stream",
            )
        return JSONResponse(
            (await service.complete(body, identity=request.state.gateway_identity)).model_dump()
        )
    except ProviderError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    except BillingError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
