# xyml-toolcall

`xyml-toolcall` is a zero-dependency Python SDK for rendering, parsing, validating, streaming, and executing LLM tool calls. It is the Python counterpart to the repository's `packages/npm/xyml-toolcall` package.

It accepts XYML by default, parses legacy QNML as well, and can recover OpenAI-style JSON, simple XML, and text key/value tool-call payloads.

## Install

After publishing to PyPI:

```bash
pip install xyml-toolcall
```

Install from this repository before publishing:

```bash
pip install ./packages/python/xyml-toolcall
```

Build a distributable wheel and source archive:

```bash
cd packages/python/xyml-toolcall
python -m pip install build
python -m build
```

## Quick start

```python
from xyml_toolcall import (
    build_tool_instructions,
    parse_tool_calls,
    render_tool_call,
)

tools = [
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
    }
]

instructions = build_tool_instructions(tools)
model_output = render_tool_call("Bash", {"command": "pwd"})
calls = parse_tool_calls(model_output, tools)

assert calls[0].name == "Bash"
assert calls[0].input == {"command": "pwd"}
```

## Public API

The Python API uses snake_case names:

```python
from xyml_toolcall import (
    ParsedToolCall,
    ProtocolSpec,
    ToolCallConfig,
    ToolCallEngine,
    ToolRuntime,
    ToolSieve,
    anthropic_tool_use_blocks,
    build_tool_instructions,
    coerce_tool_input,
    normalize_tools,
    openai_tool_calls,
    parse_markup_tool_calls,
    parse_tool_calls,
    render_tool_call,
    render_tool_calls,
    responses_tool_items,
)
```

Camel-case aliases (`parseToolCalls`, `renderToolCall`, and so on) are also exported for easier migration from the JavaScript SDK.

### Protocol configuration

```python
from xyml_toolcall import ProtocolSpec, ToolCallConfig, parse_tool_calls

config = ToolCallConfig(
    emit_protocol="XYML",
    parse_protocols=[
        ProtocolSpec("XYML"),
        ProtocolSpec("CALLML"),
        ProtocolSpec("QNML", parse_only=True),
    ],
)

calls = parse_tool_calls(text, tools, config=config)
```

`ToolCallConfig` accepts both Python names such as `emit_protocol` and JavaScript-compatible names such as `emitProtocol` when initialized from a mapping.

### Streaming

```python
from xyml_toolcall import ToolSieve

sieve = ToolSieve(tools)
for event in sieve.process_chunk(next_text_chunk):
    if event["type"] == "content":
        print(event["text"], end="")
    else:
        print(event["calls"])

for event in sieve.flush():
    print(event)
```

### Local execution

`ToolRuntime` deliberately only executes handlers that the application registers. Parsing a model response never executes any code by itself.

```python
import asyncio
from xyml_toolcall import ToolRuntime

runtime = ToolRuntime()

@runtime.tool("Bash")
def bash(arguments, metadata):
    return {"received": arguments["command"]}

results = asyncio.run(runtime.execute(calls))
```

## Development

The package has no runtime dependencies. Run its test suite with:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

For a distribution-level check, build and install the generated wheel into a
fresh virtual environment before running the tests:

```bash
python -m pip install build
python -m build
python -m venv .venv
.venv/bin/python -m pip install dist/*.whl
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
`py.typed` is included so type checkers can consume the inline public API type
annotations. Publish with `python -m twine upload dist/*` after the package
name and PyPI credentials are configured.
