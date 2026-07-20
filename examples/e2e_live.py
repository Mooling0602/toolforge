#!/usr/bin/env python3
"""Live E2E against a real upstream via ToolForge.

Usage:
  1. Start ToolForge with config pointing at a real upstream.
  2. Export TOOLFORGE_BASE / TOOLFORGE_KEY (and ensure model exists).

  python examples/e2e_live.py --mode chat
  python examples/e2e_live.py --mode chat-stream
  python examples/e2e_live.py --mode responses-stream
  python examples/e2e_live.py --mode anthropic
  python examples/e2e_live.py --mode all

Environment:
  TOOLFORGE_BASE   default http://127.0.0.1:8080
  TOOLFORGE_KEY    default sk-toolforge-demo
  TOOLFORGE_MODEL  default first model from /v1/models or demo-model
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, Optional


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


BASE = env("TOOLFORGE_BASE", "http://127.0.0.1:8080").rstrip("/")
KEY = env("TOOLFORGE_KEY", "sk-toolforge-demo")
MODEL = env("TOOLFORGE_MODEL", "")


TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather by city name",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]

TOOLS_ANTHROPIC = [
    {
        "name": "get_weather",
        "description": "Get weather by city name",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
]

TOOLS_RESPONSES = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get weather by city name",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    }
]


def _request(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    *,
    stream: bool = False,
    extra_headers: Optional[Dict[str, str]] = None,
):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=180)


def resolve_model() -> str:
    if MODEL:
        return MODEL
    try:
        with _request("GET", "/v1/models") as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            data = payload.get("data") or []
            if data:
                return str(data[0].get("id") or "demo-model")
    except Exception:
        pass
    return "demo-model"


def iter_sse(resp) -> Iterator[str]:
    while True:
        line = resp.readline()
        if not line:
            break
        yield line.decode("utf-8", errors="replace").rstrip("\r\n")


def run_chat(model: str) -> None:
    print("== chat non-stream ==")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "What is the weather in Tokyo? Use the tool."}],
        "tools": TOOLS_OPENAI,
    }
    with _request("POST", "/v1/chat/completions", body) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        mode = resp.headers.get("X-ToolForge-FC-Mode")
        print("fc_mode:", mode)
        print(json.dumps(data.get("choices", [{}])[0].get("message"), ensure_ascii=False, indent=2))


def run_chat_stream(model: str) -> None:
    print("== chat stream ==")
    body = {
        "model": model,
        "stream": True,
        "messages": [{"role": "user", "content": "What is the weather in Paris? Use the tool."}],
        "tools": TOOLS_OPENAI,
    }
    with _request("POST", "/v1/chat/completions", body, stream=True) as resp:
        print("fc_mode:", resp.headers.get("X-ToolForge-FC-Mode"))
        saw_done = False
        for line in iter_sse(resp):
            if line.startswith("data:"):
                print(line)
                if "[DONE]" in line:
                    saw_done = True
        print("saw_done:", saw_done)


def run_responses_stream(model: str) -> None:
    print("== responses stream ==")
    body = {
        "model": model,
        "stream": True,
        "input": "What is the weather in Berlin? Use the tool.",
        "tools": TOOLS_RESPONSES,
    }
    with _request("POST", "/v1/responses", body, stream=True) as resp:
        print("fc_mode:", resp.headers.get("X-ToolForge-FC-Mode"))
        events = []
        for line in iter_sse(resp):
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("data:"):
                print(line[:300])
        print("events:", events[:20], "..." if len(events) > 20 else "")
        assert any(e.startswith("response.") for e in events) or "response.created" in events


def run_anthropic(model: str) -> None:
    print("== anthropic messages ==")
    body = {
        "model": model,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "Weather in Rome? Use the tool."}],
        "tools": TOOLS_ANTHROPIC,
    }
    with _request(
        "POST",
        "/v1/messages",
        body,
        extra_headers={"anthropic-version": "2023-06-01"},
    ) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("fc_mode:", resp.headers.get("X-ToolForge-FC-Mode"))
        print(json.dumps(data.get("content"), ensure_ascii=False, indent=2)[:2000])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        default="chat",
        choices=["chat", "chat-stream", "responses-stream", "anthropic", "all"],
    )
    args = parser.parse_args()
    model = resolve_model()
    print(f"BASE={BASE} MODEL={model}")

    try:
        if args.mode in {"chat", "all"}:
            run_chat(model)
        if args.mode in {"chat-stream", "all"}:
            run_chat_stream(model)
        if args.mode in {"responses-stream", "all"}:
            run_responses_stream(model)
        if args.mode in {"anthropic", "all"}:
            run_anthropic(model)
    except urllib.error.HTTPError as exc:
        print("HTTPError", exc.code, exc.read().decode("utf-8", errors="replace")[:1000], file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print("ERROR", exc, file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
