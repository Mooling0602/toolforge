import json

import httpx
from fastapi.testclient import TestClient
from app.engine.xyml import render_tool_call

from app.main import create_app
from app.config import AppConfig, ClientAuthConfig, FeaturesConfig, UpstreamConfig


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


def _sse_body(chunks):
    parts = []
    for c in chunks:
        parts.append(f"data: {json.dumps(c, ensure_ascii=False)}\n\n")
    parts.append("data: [DONE]\n\n")
    return "".join(parts).encode("utf-8")


def test_responses_stream_prompt_fc(monkeypatch):
    config = AppConfig(
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                type="openai_compat",
                base_url="http://upstream.test/v1",
                models=["gpt-demo"],
                native_fc=False,
                is_default=True,
            )
        ],
        features=FeaturesConfig(enable_cli_profiles=False),
    )
    app = create_app(config)
    markup = render_tool_call("get_weather", {"city": "Oslo"})

    # Stream markup in two pieces
    half = len(markup) // 2
    pieces = [markup[:half], markup[half:]]

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body.get("stream") is True
        chunks = []
        for i, piece in enumerate(pieces):
            chunks.append(
                {
                    "id": "chatcmpl-s",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-demo",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": piece} if i else {"role": "assistant", "content": piece},
                            "finish_reason": None,
                        }
                    ],
                }
            )
        chunks.append(
            {
                "id": "chatcmpl-s",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-demo",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(chunks),
        )

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = _MockTransport(handler)
        kwargs.setdefault("base_url", "http://upstream.test/v1")
        return real(*args, **kwargs)

    monkeypatch.setattr("app.upstream.openai.httpx.AsyncClient", factory)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "gpt-demo",
                "stream": True,
                "input": "weather Oslo?",
                "tools": [
                    {
                        "type": "function",
                        "name": "get_weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ],
            },
        ) as resp:
            assert resp.status_code == 200, resp.read()
            text = "".join(resp.iter_text())
            assert "response.created" in text
            assert "response.completed" in text or "function_call" in text
            assert "get_weather" in text
            assert "Oslo" in text


def test_openai_chat_stream_prompt_stable(monkeypatch):
    config = AppConfig(
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                type="openai_compat",
                base_url="http://upstream.test/v1",
                models=["m"],
                native_fc=False,
                is_default=True,
            )
        ],
        features=FeaturesConfig(enable_cli_profiles=False),
    )
    app = create_app(config)
    markup = render_tool_call("get_weather", {"city": "Lisbon"})

    async def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": markup}, "finish_reason": None}],
            },
            {
                "id": "c1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "m",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body(chunks),
        )

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = _MockTransport(handler)
        kwargs.setdefault("base_url", "http://upstream.test/v1")
        return real(*args, **kwargs)

    monkeypatch.setattr("app.upstream.openai.httpx.AsyncClient", factory)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "m",
                "stream": True,
                "messages": [{"role": "user", "content": "weather?"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"],
                            },
                        },
                    }
                ],
            },
        ) as resp:
            assert resp.status_code == 200
            text = "".join(resp.iter_text())
            assert "tool_calls" in text
            assert "get_weather" in text
            assert "[DONE]" in text
