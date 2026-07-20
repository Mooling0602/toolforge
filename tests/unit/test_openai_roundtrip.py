import json

import httpx
import pytest
from fastapi.testclient import TestClient
from app.engine.xyml import render_tool_call

from app.main import create_app
from app.config import (
    AppConfig,
    ClientAuthConfig,
    FeaturesConfig,
    ServerConfig,
    UpstreamConfig,
)


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


@pytest.fixture
def prompt_app(monkeypatch):
    config = AppConfig(
        server=ServerConfig(host="127.0.0.1", port=8080),
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                type="openai_compat",
                base_url="http://upstream.test/v1",
                api_key="sk-up",
                models=["demo-model"],
                native_fc=False,
                is_default=True,
            )
        ],
        features=FeaturesConfig(fc_mode="auto", inject_protocol="XYML"),
    )
    app = create_app(config)

    markup = render_tool_call("get_weather", {"city": "Tokyo"})

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        # Path B must not forward tools
        assert "tools" not in body
        assert any(
            "TOOL CALL PROTOCOL" in str(m.get("content") or "")
            for m in body.get("messages") or []
            if isinstance(m, dict)
        )
        payload = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 1,
            "model": body.get("model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": markup},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return httpx.Response(200, json=payload)

    # Patch AsyncClient used by upstream
    real_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = _MockTransport(handler)
        kwargs.setdefault("base_url", "http://upstream.test/v1")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.upstream.openai.httpx.AsyncClient", client_factory)
    return app


def test_prompt_fc_non_stream(prompt_app):
    with TestClient(prompt_app) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "demo-model",
                "messages": [{"role": "user", "content": "weather in Tokyo?"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "weather",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"],
                            },
                        },
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert resp.headers.get("X-ToolForge-FC-Mode") == "prompt"
        message = data["choices"][0]["message"]
        assert data["choices"][0]["finish_reason"] == "tool_calls"
        assert message["tool_calls"][0]["function"]["name"] == "get_weather"
        args = json.loads(message["tool_calls"][0]["function"]["arguments"])
        assert args["city"] == "Tokyo"


def test_native_passthrough_keeps_tools(monkeypatch):
    config = AppConfig(
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                type="openai_compat",
                base_url="http://upstream.test/v1",
                api_key="sk-up",
                models=["gpt-demo"],
                native_fc=True,
                is_default=True,
            )
        ],
        features=FeaturesConfig(fc_mode="auto"),
    )
    app = create_app(config)
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-n",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-demo",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_abc",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city":"Osaka"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    real_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = _MockTransport(handler)
        kwargs.setdefault("base_url", "http://upstream.test/v1")
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("app.upstream.openai.httpx.AsyncClient", client_factory)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "gpt-demo",
                "messages": [{"role": "user", "content": "weather?"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                        },
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("X-ToolForge-FC-Mode") == "native"
        assert "tools" in seen["body"]
        assert "TOOL CALL PROTOCOL" not in json.dumps(seen["body"], ensure_ascii=False)
        data = resp.json()
        assert data["choices"][0]["finish_reason"] == "tool_calls"


def test_auth_rejects_bad_key():
    config = AppConfig(
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                base_url="http://upstream.test/v1",
                models=["m"],
                is_default=True,
            )
        ],
    )
    with TestClient(create_app(config)) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer wrong"},
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
