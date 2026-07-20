import json

import httpx
from fastapi.testclient import TestClient
from xyml_toolcall import render_tool_call

from toolforge.app import create_app
from toolforge.config import AppConfig, ClientAuthConfig, FeaturesConfig, UpstreamConfig


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.handler(request)


def test_gemini_generate_prompt_fc(monkeypatch):
    config = AppConfig(
        client_authentication=ClientAuthConfig(enabled=True, allowed_keys=["sk-test"]),
        upstreams=[
            UpstreamConfig(
                name="mock",
                type="openai_compat",
                base_url="http://upstream.test/v1",
                api_key="sk-up",
                models=["gemini-demo"],
                native_fc=False,
                is_default=True,
            )
        ],
        features=FeaturesConfig(fc_mode="auto", enable_cli_profiles=False),
    )
    app = create_app(config)
    markup = render_tool_call("get_weather", {"city": "Seoul"})

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-g",
                "object": "chat.completion",
                "created": 1,
                "model": "gemini-demo",
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

    monkeypatch.setattr("toolforge.upstream.openai_compat.httpx.AsyncClient", factory)

    with TestClient(app) as client:
        resp = client.post(
            "/v1beta/models/gemini-demo:generateContent",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "contents": [
                    {"role": "user", "parts": [{"text": "weather in Seoul?"}]}
                ],
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "get_weather",
                                "description": "weather",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                    "required": ["city"],
                                },
                            }
                        ]
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        fcs = [p for p in parts if "functionCall" in p]
        assert fcs[0]["functionCall"]["name"] == "get_weather"
        assert fcs[0]["functionCall"]["args"]["city"] == "Seoul"
