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


def test_responses_prompt_fc(monkeypatch):
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
    markup = render_tool_call("get_weather", {"city": "Rome"})

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-r",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-demo",
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
            "/v1/responses",
            headers={"Authorization": "Bearer sk-test"},
            json={
                "model": "gpt-demo",
                "input": "weather Rome?",
                "tools": [
                    {
                        "type": "function",
                        "name": "get_weather",
                        "description": "weather",
                        "parameters": {
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
        assert data["object"] == "response"
        fcs = [o for o in data["output"] if o.get("type") == "function_call"]
        assert fcs[0]["name"] == "get_weather"
        assert json.loads(fcs[0]["arguments"])["city"] == "Rome"
