"""Golden test: compare refactored output against saved golden.json."""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from app.engine.xyml import (
    ToolCallConfig, ToolSieve, build_tool_instructions, coerce_tool_input, normalize_tools,
    parse_markup_tool_calls, parse_tool_calls, render_tool_call, render_tool_calls,
    openai_tool_calls, responses_tool_items, anthropic_tool_use_blocks, ToolCall,
)

HERE = Path(__file__).resolve().parent
golden_path = HERE / "golden.json"
if not golden_path.exists():
    print("golden.json not found. Run 'python bench_refactor.py golden' first.")
    sys.exit(1)

golden = json.loads(golden_path.read_text(encoding="utf-8"))

WEATHER_TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "description": "按城市查天气", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "unit": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "send_email", "description": "发送邮件", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "attachments": {"type": "array", "items": {"type": "string"}}}, "required": ["to", "subject", "body"]}}},
]
EXEC_TOOLS = [
    {"type": "function", "function": {"name": "Bash", "description": "Run shell", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "Read", "description": "Read file", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "Write", "description": "Write file", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}}},
]

def to_jsonable(calls):
    return [{"id": c.id, "name": c.name, "input": c.input} for c in calls]

def strip_ids(obj):
    """Recursively remove 'id' keys for comparison (random IDs differ per run)."""
    if isinstance(obj, dict):
        return {k: strip_ids(v) for k, v in obj.items() if k != "id" and k != "call_id"}
    if isinstance(obj, list):
        return [strip_ids(i) for i in obj]
    return obj

def strip_id_from_calls(calls):
    return [{"name": c["name"], "input": c["input"]} for c in calls]

errors = []
all_keys = set(golden.keys())

# ── parse corpus ────────────────────────────────────────────────
CORPUS_PARSE = [
    ("xyml_simple", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city"><![CDATA[Tokyo]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("xyml_bool_null", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city">Tokyo</|XYML|parameter>\n    <|XYML|parameter name="unit">metric</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("xyml_array", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="send_email">\n    <|XYML|parameter name="to"><![CDATA[a@b.com]]></|XYML|parameter>\n    <|XYML|parameter name="subject">hi</|XYML|parameter>\n    <|XYML|parameter name="body"><![CDATA[hello world]]></|XYML|parameter>\n    <|XYML|parameter name="attachments">["a.pdf","b.pdf"]</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("xyml_short_close", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city"><![CDATA[Tokyo]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML>'),
    ("xyml_no_protocol_name", WEATHER_TOOLS, '<|tool_calls>\n  <|invoke name="get_weather">\n    <|parameter name="city"><![CDATA[Tokyo]]></|parameter>\n  </|invoke>\n</|tool_calls>'),
    ("xyml_markdown_fence", WEATHER_TOOLS, 'Here is the call:\n```xml\n<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city">Shanghai</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>\n```'),
    ("xyml_fullwidth", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name＝"get_weather">\n    <|XYML|parameter name＝"city">Tokyo</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("qnml_simple", WEATHER_TOOLS, '<|QNML|tool_calls>\n  <|QNML|invoke name="get_weather">\n    <|QNML|parameter name="city"><![CDATA[Paris]]></|QNML|parameter>\n  </|QNML|invoke>\n</|QNML|tool_calls>'),
    ("xml_tool_call", WEATHER_TOOLS, '<tool_call>\n  {"name": "get_weather", "arguments": {"city": "NYC"}}\n</tool_call>'),
    ("xml_tool_use", WEATHER_TOOLS, '<tool_use name="get_weather">\n  <city>Berlin</city>\n</tool_use>'),
    ("xml_function_json", WEATHER_TOOLS, '<function name="send_email">{"to":"x@y.z","subject":"s","body":"b"}</function>'),
    ("json_tool_calls", WEATHER_TOOLS, '{"tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": {"city": "London"}}}]}'),
    ("json_repair", WEATHER_TOOLS, 'name = "get_weather"\narguments = {"city": "Madrid"}'),
    ("text_kv", WEATHER_TOOLS, 'function.name: get_weather\nfunction.arguments: {"city": "Tokyo"}'),
    ("nested_xml_items", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="send_email">\n    <|XYML|parameter name="attachments"><item>a.pdf</item><item>b.pdf</item></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("raw_string_param", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="send_email">\n    <|XYML|parameter name="body"><![CDATA[line1\nline2\nline3]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("plain_text_no_call", WEATHER_TOOLS, "今天东京天气不错，适合散步。"),
    ("exec_aliases", EXEC_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="Bash">\n    <|XYML|parameter name="command"><![CDATA[ls -la]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("exec_safe_alias_short", EXEC_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="Read">\n    <|XYML|parameter name="path">/etc/hosts</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("unknown_tool_drop", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="no_such_tool">\n    <|XYML|parameter name="city">X</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("missing_required_drop", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="unit">k</|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("dedupe", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather"><|XYML|parameter name="city">a</|XYML|parameter></|XYML|invoke>\n  <|XYML|invoke name="get_weather"><|XYML|parameter name="city">a</|XYML|parameter></|XYML|invoke>\n  <|XYML|invoke name="get_weather"><|XYML|parameter name="city">b</|XYML|parameter></|XYML|invoke>\n</|XYML|tool_calls>'),
    ("multi_tools", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather"><|XYML|parameter name="city">a</|XYML|parameter></|XYML|invoke>\n  <|XYML|invoke name="send_email"><|XYML|parameter name="to">e@e.e</|XYML|parameter><|XYML|parameter name="subject">s</|XYML|parameter><|XYML|parameter name="body">b</|XYML|parameter></|XYML|invoke>\n</|XYML|tool_calls>'),
    ("polluted_path", EXEC_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="Read">\n    <|XYML|parameter name="file_path"><![CDATA[</|XYML|invoke> hijack]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>'),
    ("unclosed_block", WEATHER_TOOLS, '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city">Tokyo'),
    ("plain_json_inside_text", WEATHER_TOOLS, '{"response": "I cannot access realtime data", "ok": true}'),
]

for name, tools, text in CORPUS_PARSE:
    key = f"parse:{name}"
    try:
        actual = to_jsonable(parse_tool_calls(text, tools))
    except Exception as exc:
        actual = {"__error__": f"{type(exc).__name__}: {exc}"}
    expected = golden.get(key)
    if strip_ids(actual) != strip_ids(expected):
        errors.append(f"PARSE MISMATCH {key}: expected={expected} actual={actual}")

# ── render corpus ───────────────────────────────────────────────
CORPUS_RENDER = [
    ("render_simple", "get_weather", {"city": "Tokyo", "unit": "metric"}),
    ("render_string_cdata", "send_email", {"to": "a@b.com", "subject": "hi", "body": "line1\nline2"}),
    ("render_array", "send_email", {"attachments": ["a.pdf", "b.pdf"]}),
    ("render_bool_null", "get_weather", {"debug": True, "limit": None}),
]
for name, tool_name, args in CORPUS_RENDER:
    key = f"render:{name}"
    actual = render_tool_call(tool_name, args)
    expected = golden.get(key)
    if actual != expected:
        errors.append(f"RENDER MISMATCH {key}")

# ── instructions ────────────────────────────────────────────────
for cfg_key in ("instructions:default", "instructions:minimal", "instructions:exec"):
    expected = golden.get(cfg_key)
    if cfg_key == "instructions:exec":
        actual = build_tool_instructions(EXEC_TOOLS)
    elif cfg_key == "instructions:minimal":
        actual = build_tool_instructions(WEATHER_TOOLS, config=ToolCallConfig({"prompt_style": "minimal"}))
    else:
        actual = build_tool_instructions(WEATHER_TOOLS)
    if actual != expected:
        errors.append(f"INSTRUCTION MISMATCH {cfg_key}")

# ── output formatters ───────────────────────────────────────────
calls = parse_tool_calls('<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city"><![CDATA[Tokyo]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>', WEATHER_TOOLS)
for fmt_key in ("output:openai", "output:responses", "output:anthropic"):
    expected = golden.get(fmt_key)
    if fmt_key == "output:openai":
        actual = openai_tool_calls(calls)
    elif fmt_key == "output:responses":
        actual = responses_tool_items(calls)
    else:
        actual = anthropic_tool_use_blocks(calls)
    if strip_ids(actual) != strip_ids(expected):
        errors.append(f"OUTPUT MISMATCH {fmt_key}: expected={expected} actual={actual}")

# ── sieve ───────────────────────────────────────────────────────
SIEVE_CHUNKS = [
    "好的我来。\n<|XYML|tool", "_calls>\n  <|XYML|invoke name= \"get",
    "_weather\">\n    <|XYML|parameter name=\"city\"><![CDATA[T",
    "okyo]]></|XYML|parameter>\n  </|XYML|",
    "invoke>\n</|XYML|tool_calls>",
]
sieve = ToolSieve(WEATHER_TOOLS)
events = []
for p in SIEVE_CHUNKS:
    events.append(sieve.process_chunk(p))
events.append(sieve.flush())
sieve_actual = [
    {"type": e.get("type"), "text": e.get("text"), "calls": to_jsonable(e.get("calls") or [])}
    for evs in events for e in evs
]
sieve_expected = golden.get("sieve:sieve_split_call")
if strip_ids(sieve_actual) != strip_ids(sieve_expected):
    errors.append(f"SIEVE MISMATCH sieve_split_call: expected={sieve_expected} actual={sieve_actual}")

# ── parse_markup_tool_calls ─────────────────────────────────────
pm_actual = to_jsonable(parse_markup_tool_calls(
    '<|XYML|tool_calls>\n  <|XYML|invoke name="get_weather">\n    <|XYML|parameter name="city"><![CDATA[Tokyo]]></|XYML|parameter>\n  </|XYML|invoke>\n</|XYML|tool_calls>',
    WEATHER_TOOLS,
))
pm_expected = golden.get("parse_markup:default")
if strip_ids(pm_actual) != strip_ids(pm_expected):
    errors.append(f"PARSE_MARKUP MISMATCH")

# ── Summary ─────────────────────────────────────────────────────
total = len(golden)
if errors:
    for e in errors[:20]:
        print(f"FAIL: {e}")
    print(f"\n{len(errors)}/{total} tests FAILED")
    sys.exit(1)
else:
    print(f"ALL {total} golden tests PASSED")