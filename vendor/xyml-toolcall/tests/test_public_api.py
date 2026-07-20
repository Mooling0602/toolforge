import asyncio
import json
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from xyml_toolcall import (  # noqa: E402
    ProtocolSpec,
    ToolCallConfig,
    ToolCallEngine,
    ToolRuntime,
    ToolSieve,
    anthropic_tool_use_blocks,
    build_tool_instructions,
    openai_tool_calls,
    parse_tool_calls,
    parseToolCalls,
    render_tool_call,
    renderToolCall,
    responses_tool_items,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run a shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "filters": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                "required": ["query"],
            },
        },
    },
]


class PublicApiTests(unittest.TestCase):
    def test_renders_and_parses_default_xyml(self):
        block = render_tool_call("Bash", {"command": "pwd"})
        self.assertIn("<|XYML|tool_calls>", block)
        calls = parse_tool_calls(block, TOOLS)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "Bash")
        self.assertEqual(calls[0].input, {"command": "pwd"})

    def test_parses_legacy_qnml_by_default(self):
        block = """
<|QNML|tool_calls>
  <|QNML|invoke name="Bash">
    <|QNML|parameter name="command"><![CDATA[ls]]></|QNML|parameter>
  </|QNML|invoke>
</|QNML|tool_calls>
"""
        calls = parse_tool_calls(block, TOOLS)
        self.assertEqual(calls[0].input, {"command": "ls"})

    def test_supports_multiple_custom_protocols(self):
        config = ToolCallConfig(
            {
                "emit_protocol": "XYML",
                "parse_protocols": [
                    ProtocolSpec("XYML"),
                    ProtocolSpec("MYML"),
                    ProtocolSpec("CALLML"),
                ],
            }
        )
        block = """
<|CALLML|tool_calls>
  <|CALLML|invoke name="Bash">
    <|CALLML|parameter name="command"><![CDATA[whoami]]></|CALLML|parameter>
  </|CALLML|invoke>
</|CALLML|tool_calls>
"""
        calls = parse_tool_calls(block, TOOLS, config=config)
        self.assertEqual(calls[0].input["command"], "whoami")

    def test_parses_json_and_coerces_schema_arrays(self):
        payload = {
            "tool_calls": [
                {
                    "id": "call_test",
                    "function": {
                        "name": "search",
                        "arguments": json.dumps(
                            {"query": "abc", "filters": '{"kind":"file"}'}
                        ),
                    },
                }
            ]
        }
        calls = parse_tool_calls(json.dumps(payload), TOOLS)
        self.assertEqual(calls[0].id, "call_test")
        self.assertEqual(calls[0].input["filters"], [{"kind": "file"}])

    def test_builds_instructions_and_compatibility_outputs(self):
        instructions = build_tool_instructions(TOOLS)
        self.assertIn("XYML TOOL CALL PROTOCOL", instructions)
        calls = parse_tool_calls(render_tool_call("Bash", {"command": "pwd"}), TOOLS)
        self.assertEqual(openai_tool_calls(calls)[0]["type"], "function")
        self.assertEqual(responses_tool_items(calls)[0]["type"], "function_call")
        self.assertEqual(anthropic_tool_use_blocks(calls)[0]["type"], "tool_use")

    def test_sieve_captures_streamed_tool_calls(self):
        block = render_tool_call("Bash", {"command": "pwd"})
        sieve = ToolSieve(TOOLS)
        events = []
        events.extend(sieve.process_chunk("before "))
        events.extend(sieve.process_chunk(block[:20]))
        events.extend(sieve.process_chunk(block[20:]))
        events.extend(sieve.flush())
        self.assertEqual(events[0], {"type": "content", "text": "before "})
        tool_event = next(event for event in events if event["type"] == "tool_calls")
        self.assertEqual(tool_event["calls"][0].name, "Bash")

    def test_runtime_executes_registered_handlers(self):
        runtime = ToolRuntime()

        @runtime.tool("Bash")
        def bash(arguments, metadata):
            self.assertEqual(metadata["call"].name, "Bash")
            return {"command": arguments["command"]}

        calls = parse_tool_calls(render_tool_call("Bash", {"command": "pwd"}), TOOLS)
        results = asyncio.run(runtime.execute(calls))
        self.assertEqual(results[0]["output"], {"command": "pwd"})

    def test_unknown_tool_keep_policy(self):
        config = ToolCallConfig({"unknown_tool": "keep", "missing_required": "keep"})
        calls = parse_tool_calls(
            render_tool_call("custom_tool", {"value": 1}), TOOLS, config=config
        )
        self.assertEqual(calls[0].name, "custom_tool")

    def test_engine_and_camel_case_exports(self):
        engine = ToolCallEngine.with_protocols(emit="XYML", parse=["XYML", "QNML"])
        block = engine.render("Bash", {"command": "pwd"})
        self.assertEqual(engine.parse(block, TOOLS)[0].name, "Bash")
        self.assertEqual(parseToolCalls(renderToolCall("Bash", {"command": "pwd"}), TOOLS)[0].name, "Bash")


if __name__ == "__main__":
    unittest.main()
