"""
Test ToolForge (on :8080) → cnb2api (on :7863) integration.

Tests:
1. health check
2. basic chat (no tools)
3. single-turn tool call
4. multi-turn: tool call → result → final answer
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

BASE = "http://127.0.0.1:8080"
API_KEY = "sk-toolforge-demo"
MODEL = "@makers/deepseek-v4-flash"

WEATHER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=60)


def test_health():
    r = httpx.get(f"{BASE}/health", timeout=5)
    print(f"  health: {r.status_code} {r.json()}")
    assert r.status_code == 200


def test_basic_chat():
    """No tools — verify plain text flows through."""
    r = client().post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "Hello! Say 'hello world' back."}],
            "stream": False,
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    assert data["choices"][0]["finish_reason"] == "stop"
    assert not data["choices"][0]["message"].get("tool_calls")
    print(f"  basic_chat: {text[:60]}...")
    print(f"  finish_reason: {data['choices'][0]['finish_reason']}")


def test_single_tool():
    """Single tool call — model should output XYML, ToolForge should parse it."""
    r = client().post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. When asked about weather, use the get_weather tool."},
                {"role": "user", "content": "What's the weather like in Tokyo?"},
            ],
            "tools": WEATHER_TOOLS,
            "stream": False,
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    data = r.json()
    msg = data["choices"][0]["message"]
    fr = data["choices"][0]["finish_reason"]
    tc = msg.get("tool_calls", [])
    content = msg.get("content", "")
    print(f"  single_tool:")
    print(f"    finish_reason: {fr}")
    print(f"    content: {content[:80] if content else '(empty)'}")
    if tc:
        print(f"    tool_calls[{len(tc)}]: {[t['function']['name'] for t in tc]}")
        for t in tc:
            print(f"      {t['function']['name']}({t['function']['arguments']})")
    else:
        print(f"    WARNING: no tool_calls — model refused to call tool")
    return tc, msg, data


def test_multi_turn():
    """Multi-turn: tool call → result → final answer → second tool call → result → final."""
    msgs = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools available to answer questions."},
        {"role": "user", "content": "What's the weather in Tokyo and then send an email to admin@test.com with the result?"},
    ]
    max_turns = 6
    tool_calls_seen = 0

    for turn in range(max_turns):
        print(f"\n  --- Turn {turn + 1} ---")
        r = client().post(
            "/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": msgs,
                "tools": WEATHER_TOOLS,
                "stream": False,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        data = r.json()
        msg = data["choices"][0]["message"]
        fr = data["choices"][0]["finish_reason"]
        content = msg.get("content", "")
        tc = msg.get("tool_calls", [])

        if content:
            print(f"  assistant: {content[:80]}...")
        print(f"  finish_reason: {fr}")

        if tc:
            tool_calls_seen += len(tc)
            print(f"  tool_calls[{len(tc)}]:")
            for t in tc:
                fc = t["function"]
                print(f"    {t['id']}: {fc['name']}({fc['arguments']})")
                # Simulate tool result
                name = fc["name"]
                args = json.loads(fc["arguments"])
                if name == "get_weather":
                    result = {"city": args.get("city", "unknown"), "temperature": "22°C", "condition": "sunny"}
                elif name == "send_email":
                    result = {"status": "sent", "to": args.get("to", "unknown")}
                else:
                    result = {"status": "unknown_tool"}
                msgs.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tc,
                })
                msgs.append({
                    "role": "tool",
                    "tool_call_id": t["id"],
                    "content": json.dumps(result),
                })
        else:
            # Final answer
            print(f"  FINAL: {content[:120] if content else '(empty)'}")
            break

    print(f"\n  total_tool_calls_seen: {tool_calls_seen}")
    assert tool_calls_seen >= 1, "Expected at least 1 tool call across multi-turn"
    return tool_calls_seen


def test_streaming_tool():
    """Streaming mode with tools."""
    print("  streaming tool call...")
    chunks: List[str] = []
    tc_parts: List[Dict[str, Any]] = []
    with client() as cl:
        with cl.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "What's the weather like in Beijing?"}],
                "tools": WEATHER_TOOLS,
                "stream": True,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
        ) as resp:
            for line in resp.iter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        chunks.append(chunk)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        tc = delta.get("tool_calls")
                        if tc:
                            tc_parts.extend(tc)
                    except json.JSONDecodeError:
                        pass
    print(f"    chunks: {len(chunks)}, tool_calls_parts: {len(tc_parts)}")
    assert len(tc_parts) > 0, "Expected tool_calls in streaming"
    if tc_parts:
        name = tc_parts[0].get("function", {}).get("name", "?")
        print(f"    first tool: {name}")
    return tc_parts


if __name__ == "__main__":
    print("=== ToolForge Integration Tests ===")

    print("\n1. health check")
    test_health()

    print("\n2. basic chat (no tools)")
    test_basic_chat()

    print("\n3. single-turn tool call")
    tc, _, _ = test_single_tool()
    if tc:
        print("  PASS: got tool call")
    else:
        print("  WARN: no tool call (model may not have followed instructions)")

    print("\n4. multi-turn tool call")
    n_tc = test_multi_turn()
    if n_tc >= 2:
        print(f"  PASS: {n_tc} tool calls across multiple turns")
    elif n_tc >= 1:
        print(f"  PASS: {n_tc} tool call (single call)")
    else:
        print("  WARN: no tool calls in multi-turn")

    print("\n5. streaming tool call")
    ts = test_streaming_tool()

    print("\n=== All tests complete ===")