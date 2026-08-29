from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from parrot_gateway.core.config import Settings
from parrot_gateway.domain.errors import ProviderError
from parrot_gateway.domain.models import IRChatRequest, ModelList
from parrot_gateway.infrastructure.provider_executor import ProviderExecutor
from parrot_gateway.providers import (
    DeepseekAdaptor,
    KimiAdaptor,
    OpenAIAdaptor,
    QwenAdaptor,
)
from parrot_gateway.services.chat_completion import ChatCompletionService
from parrot_gateway.services.model_router import ModelRouter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    openai = OpenAIAdaptor.from_settings(
        settings,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
    )
    deepseek = DeepseekAdaptor.from_settings(
        settings,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key or settings.upstream_api_key,
    )
    kimi = KimiAdaptor.from_settings(
        settings,
        base_url=settings.kimi_base_url,
        api_key=settings.kimi_api_key or settings.upstream_api_key,
    )
    qwen = QwenAdaptor.from_settings(
        settings,
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key or settings.upstream_api_key,
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
    service = ChatCompletionService(router, ProviderExecutor())
    app.state.settings = settings
    app.state.service = service
    app.state.router = router
    yield
    clients = {id(adaptor.client): adaptor.client for adaptor in (openai, deepseek, kimi, qwen)}
    for client in clients.values():
        await client.aclose()


app = FastAPI(title="Parrot Gateway", version="0.1.0", lifespan=lifespan)


def get_chat_service(request: Request) -> ChatCompletionService:
    return request.app.state.service


# Backward-compatible dependency name for integrations using the initial API.
get_provider = get_chat_service


async def verify_gateway_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected_key: str | None = request.app.state.settings.gateway_api_key
    if expected_key and authorization != f"Bearer {expected_key}":
        raise HTTPException(status_code=401, detail={"message": "Invalid gateway API key"})


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
    body: IRChatRequest,
    service: Annotated[ChatCompletionService, Depends(get_provider)],
) -> JSONResponse | StreamingResponse:
    try:
        if body.stream:
            return StreamingResponse(service.stream(body), media_type="text/event-stream")
        return JSONResponse((await service.complete(body)).model_dump())
    except ProviderError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
