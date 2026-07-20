from app.fc.obfuscation import deobfuscate_calls, obfuscate_tools
from app.fc.profiles import detect_tool_profile, profile_instruction_block
from app.fc.recovery import build_retry_user_message, is_tool_call_truncated, parse_with_recovery_hint
from app.models.canonical import ToolCall, ToolDef


def test_detect_claude_code_profile():
    tools = [
        ToolDef(name="Read"),
        ToolDef(name="Write"),
        ToolDef(name="Bash"),
        ToolDef(name="Agent"),
    ]
    profile = detect_tool_profile(tools)
    assert profile.id == "claude_code"
    assert "PascalCase" in profile_instruction_block(profile)


def test_obfuscation_roundtrip():
    tools = [ToolDef(name="Read", description="read file", parameters={"type": "object"})]
    safe_tools, mapping = obfuscate_tools(tools)
    assert safe_tools[0].name == "fs_open_file"
    calls = [ToolCall(id="1", name="fs_open_file", arguments={"file_path": "a.py"})]
    restored = deobfuscate_calls(calls, mapping)
    assert restored[0].name == "Read"


def test_truncation_detection():
    text = "<|XYML|tool_calls>\n  <|XYML|invoke name=\"x\">\n"
    assert is_tool_call_truncated(text) is True
    complete = text + "  </|XYML|invoke>\n</|XYML|tool_calls>"
    assert is_tool_call_truncated(complete) is False


def test_parse_with_recovery_hint_truncated():
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
    # Open marker present, no close, and required args missing so parse yields nothing
    text = "<|XYML|tool_calls>\n  <|XYML|invoke name=\"get_weather\">\n    <|XYML|parameter name=\"city\"><![CDATA["
    calls, reason = parse_with_recovery_hint(text, tools)
    assert calls == []
    assert reason == "truncated"
    msg = build_retry_user_message(original_output=text, reason="truncated")
    assert "truncated" in msg.lower() or "COMPLETE" in msg
