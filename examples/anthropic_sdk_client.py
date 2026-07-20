"""Minimal Anthropic-style request against ToolForge /v1/messages."""

import json
import urllib.request

body = {
    "model": "claude-demo",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "What is the weather in Tokyo?"}],
    "tools": [
        {
            "name": "get_weather",
            "description": "Get weather by city",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ],
}

req = urllib.request.Request(
    "http://127.0.0.1:8080/v1/messages",
    data=json.dumps(body).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer sk-toolforge-demo",
        "anthropic-version": "2023-06-01",
    },
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode("utf-8"))
