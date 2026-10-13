"""The model seam. The agent depends on `LLMProvider` only; vendors live behind it."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import httpx

from .types import LLMReply, Message, ToolCall, ToolSpec


class ProviderError(Exception):
    """The provider failed. Never carries credentials or response bodies."""


class LLMProvider(Protocol):
    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 timeout_s: float) -> LLMReply: ...


class ScriptedProvider:
    """Replays canned replies (or callables). For tests, including adversarial ones."""

    def __init__(self, replies: Sequence[LLMReply | Callable[[Sequence[Message]], LLMReply]
                                         | Exception]) -> None:
        self._r = list(replies)
        self.calls: list[list[Message]] = []

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 timeout_s: float) -> LLMReply:
        self.calls.append(list(messages))
        if not self._r:
            raise ProviderError("script exhausted")
        r = self._r.pop(0)
        if isinstance(r, Exception):
            raise r
        return r(messages) if callable(r) else r


class OpenAICompatProvider:
    """Chat-completions with tool calling (OpenAI, OpenRouter, vLLM, Ollama and similar)."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 transport: httpx.BaseTransport | None = None, max_tokens: int = 900) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key, self._model, self._max = api_key, model, max_tokens
        self._client = httpx.Client(transport=transport, follow_redirects=False)

    @staticmethod
    def _wire(m: Message) -> dict[str, Any]:
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
        d: dict[str, Any] = {"role": m.role, "content": m.content or None}
        if m.tool_calls:
            d["tool_calls"] = [{"id": c.id, "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                               for c in m.tool_calls]
        return d

    def complete(self, messages: Sequence[Message], tools: Sequence[ToolSpec],
                 timeout_s: float) -> LLMReply:
        body: dict[str, Any] = {
            "model": self._model, "temperature": 0, "max_tokens": self._max,
            "messages": [self._wire(m) for m in messages],
            "tools": [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools],
        }
        try:
            resp = self._client.post(self._url, json=body, timeout=timeout_s,
                                     headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise ProviderError(f"transport error: {type(e).__name__}") from None
        if resp.status_code != 200:
            raise ProviderError(f"provider returned HTTP {resp.status_code}")
        try:
            msg = resp.json()["choices"][0]["message"]
            calls = tuple(
                ToolCall(str(c["id"]), str(c["function"]["name"]),
                         json.loads(c["function"].get("arguments") or "{}"))
                for c in (msg.get("tool_calls") or []))
            text = msg.get("content")
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("malformed provider response") from None
        if not isinstance(text, (str, type(None))) or any(
                not isinstance(c.args, dict) for c in calls):
            raise ProviderError("malformed provider response")
        return LLMReply(text=text, tool_calls=calls)
