from toolforge.fc.inject import build_instructions, inject_prompt_messages, render_history_messages
from toolforge.fc.parse import parse_text_to_calls, to_openai_tool_calls
from toolforge.models.canonical import Message, ToolCall, ToolDef
from xyml_toolcall import render_tool_call


TOOLS = [
    ToolDef(
        name="get_weather",
        description="Get weather by city",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
]


def test_build_instructions_contains_protocol():
    text = build_instructions(TOOLS, protocol="XYML")
    assert "TOOL CALL PROTOCOL" in text
    assert "get_weather" in text


def test_history_renders_tool_result():
    messages = [
        Message(role="user", content="weather?"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="call_1", name="get_weather", arguments={"city": "Tokyo"})],
        ),
        Message(role="tool", content='{"temp": 20}', tool_call_id="call_1", name="get_weather"),
    ]
    history = render_history_messages(messages, protocol="XYML")
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert "get_weather" in history[1]["content"]
    assert history[2]["role"] == "user"
    assert "Tool Result" in history[2]["content"]


def test_inject_prepends_system_instructions():
    messages = [Message(role="user", content="hi")]
    out = inject_prompt_messages(messages, TOOLS, protocol="XYML")
    assert out[0]["role"] == "system"
    assert "TOOL CALL PROTOCOL" in out[0]["content"]
    assert out[1]["role"] == "user"


def test_parse_rendered_tool_call():
    markup = render_tool_call("get_weather", {"city": "Paris"})
    calls = parse_text_to_calls(markup, TOOLS, protocol="XYML")
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].arguments.get("city") == "Paris"
    openai = to_openai_tool_calls(calls)
    assert openai[0]["type"] == "function"
    assert openai[0]["function"]["name"] == "get_weather"
