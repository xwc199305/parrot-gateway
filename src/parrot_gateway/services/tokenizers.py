from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx


class Tokenizer(ABC):
    @abstractmethod
    async def count_messages(self, model: str, messages: list[dict[str, Any]]) -> int:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class DeepseekTokenizer(Tokenizer):
    """Local tokenizer backed by the checked-in DeepSeek V4 tokenizer.json."""

    def __init__(self, tokenizer_dir: str | Path | None = None) -> None:
        directory = (
            Path(tokenizer_dir)
            if tokenizer_dir
            else Path(__file__).parents[3] / "deepseek_v4_tokenizer"
        )
        try:
            from tokenizers import Tokenizer as HFTokenizer
        except ImportError as exc:
            raise RuntimeError("DeepSeek tokenization requires the 'tokenizers' package") from exc
        self._tokenizer = HFTokenizer.from_file(str(directory / "tokenizer.json"))

    async def count_messages(self, model: str, messages: list[dict[str, Any]]) -> int:
        rendered = _render_chat_messages(messages)
        return len(self._tokenizer.encode(rendered).ids)


class KimiTokenizer(Tokenizer):
    """Kimi server-side tokenizer using the official estimate-token-count API."""

    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://api.moonshot.cn/v1/tokenizers/estimate-token-count",
    ) -> None:
        self._client = httpx.AsyncClient(timeout=15.0)
        self._api_key = api_key
        self._endpoint = endpoint

    async def count_messages(self, model: str, messages: list[dict[str, Any]]) -> int:
        response = await self._client.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": model, "messages": messages},
        )
        response.raise_for_status()
        payload = response.json()
        return int(payload["data"]["total_tokens"])

    async def aclose(self) -> None:
        await self._client.aclose()


class FallbackTokenizer(Tokenizer):
    async def count_messages(self, model: str, messages: list[dict[str, Any]]) -> int:
        return max(1, (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4)


class TokenizerRegistry:
    def __init__(self, tokenizers: dict[str, Tokenizer] | None = None) -> None:
        self._tokenizers = tokenizers or {}
        self._fallback = FallbackTokenizer()

    def register(self, provider: str, tokenizer: Tokenizer) -> None:
        self._tokenizers[provider] = tokenizer

    async def count_messages(
        self, provider: str, model: str, messages: list[dict[str, Any]]
    ) -> int:
        tokenizer = self._tokenizers.get(provider, self._fallback)
        return await tokenizer.count_messages(model, messages)

    async def aclose(self) -> None:
        for tokenizer in self._tokenizers.values():
            await tokenizer.aclose()


def _render_chat_messages(messages: list[dict[str, Any]]) -> str:
    # DeepSeek's chat template uses role markers; this preserves tool content
    # while remaining independent of transformers' optional runtime.
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        parts.append(f"<{role}>{content}")
    return "\n".join(parts) + "\n<assistant>"
