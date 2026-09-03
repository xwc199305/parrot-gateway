import json

import httpx
import pytest
from fastapi.testclient import TestClient

from parrot_gateway.domain.errors import ProviderError
from parrot_gateway.infrastructure.provider_executor import ProviderExecutor
from parrot_gateway.main import app, get_provider
from parrot_gateway.providers import DeepseekAdaptor
from parrot_gateway.services.chat_completion import ChatCompletionService
from parrot_gateway.services.model_router import ModelRouter


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GATEWAY_AUTH_MODE", "static")
    monkeypatch.setenv("DATABASE_URL", "")
    with TestClient(app) as test_client:
        yield test_client


def test_healthcheck(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_model_router_dispatches_by_longest_prefix() -> None:
    openai = object()
    deepseek = object()
    router = ModelRouter({"gpt-": openai, "deepseek-": deepseek, "deepseek-chat-": openai})

    assert router.resolve("gpt-4o") is openai
    assert router.resolve("deepseek-chat-2025") is openai
    assert router.resolve("deepseek-reasoner") is deepseek


def test_model_router_rejects_unknown_model() -> None:
    router = ModelRouter({"gpt-": object()})
    with pytest.raises(ProviderError) as error:
        router.resolve("claude-3")
    assert error.value.status_code == 400


def test_forwards_a_chat_completion(client: TestClient) -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_1",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "gpt-test",
                "choices": [],
            },
        )

    upstream = DeepseekAdaptor(
        httpx.AsyncClient(
            base_url="https://provider.example/v1/",
            transport=httpx.MockTransport(handler),
        ),
        "test-key",
    )
    app.dependency_overrides[get_provider] = lambda: ChatCompletionService(
        ModelRouter({"gpt-": upstream}), ProviderExecutor()
    )
    try:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "Hello"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["id"] == "chatcmpl_1"
    assert captured == {
        "url": "https://provider.example/v1/chat/completions",
        "payload": {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        },
    }


def test_accepts_openai_chat_completion_parameters(client: TestClient) -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_2",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "gpt-test",
                "choices": [],
            },
        )

    upstream = DeepseekAdaptor(
        httpx.AsyncClient(
            base_url="https://provider.example/v1/",
            transport=httpx.MockTransport(handler),
        ),
        "test-key",
    )
    app.dependency_overrides[get_provider] = lambda: ChatCompletionService(
        ModelRouter({"gpt-": upstream}), ProviderExecutor()
    )
    try:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-test",
                "messages": [{"role": "user", "content": "Hello"}],
                "top_p": 0.8,
                "max_completion_tokens": 128,
                "tools": [{"type": "function", "function": {"name": "lookup"}}],
                "response_format": {"type": "json_object"},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["top_p"] == 0.8
    assert captured["max_completion_tokens"] == 128
    assert captured["tools"][0]["function"]["name"] == "lookup"
    assert captured["response_format"] == {"type": "json_object"}
