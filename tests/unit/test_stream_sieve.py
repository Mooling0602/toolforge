from app.fc.parse import create_sieve
from app.models.canonical import ToolDef
from app.engine.xyml import render_tool_call


def test_sieve_emits_tool_calls_from_chunks():
    tools = [
        ToolDef(
            name="get_weather",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )
    ]
    markup = render_tool_call("get_weather", {"city": "Kyoto"})
    # hold_length must cover partial open tags; default 96 is production-safe.
    sieve = create_sieve(tools, protocol="XYML", hold_length=96)

    events = []
    # Feed in small chunks to simulate streaming
    for i in range(0, len(markup), 11):
        events.extend(sieve.process_chunk(markup[i : i + 11]))
    events.extend(sieve.flush())

    types = [e.get("type") for e in events]
    assert "tool_calls" in types
    tool_events = [e for e in events if e.get("type") == "tool_calls"]
    calls = tool_events[0]["calls"]
    assert calls[0].name == "get_weather"
