import json

import httpx
import pytest
from fastapi.testclient import TestClient
from app.engine.xyml import render_tool_call

from app.main import create_app
from app.config import AppConfig, ClientAuthConfig, FeaturesConfig, UpstreamConfig


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


def test_anthropic_prompt_fc_messages(monkeypatch):
    config = AppConfig(
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                type="openai_compat",
                base_url="http://upstream.test/v1",
                api_key="sk-up",
                models=["claude-demo"],
                native_fc=False,
                is_default=True,
            )
        ],
        features=FeaturesConfig(fc_mode="auto", enable_cli_profiles=False),
    )
    app = create_app(config)
    markup = render_tool_call("get_weather", {"city": "Berlin"})

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-a",
                "object": "chat.completion",
                "created": 1,
                "model": "claude-demo",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": markup},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = _MockTransport(handler)
        kwargs.setdefault("base_url", "http://upstream.test/v1")
        return real(*args, **kwargs)

    monkeypatch.setattr("app.upstream.openai.httpx.AsyncClient", factory)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-test", "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-demo",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": "weather Berlin?"}],
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "weather",
                        "input_schema": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["type"] == "message"
        assert data["stop_reason"] == "tool_use"
        blocks = data["content"]
        tool_blocks = [b for b in blocks if b.get("type") == "tool_use"]
        assert tool_blocks[0]["name"] == "get_weather"
        assert tool_blocks[0]["input"]["city"] == "Berlin"
