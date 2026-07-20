"""Run after installing xyml-toolcall into a Python environment."""

import asyncio

from xyml_toolcall import (
    ProtocolSpec,
    ToolCallConfig,
    ToolCallEngine,
    ToolRuntime,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Return the supplied text.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    }
]


async def main() -> None:
    config = ToolCallConfig(
        {
            "emit_protocol": "CALLML",
            "parse_protocols": [ProtocolSpec("CALLML"), ProtocolSpec("XYML")],
        }
    )
    engine = ToolCallEngine(config)
    text = engine.render("echo", {"text": "hello"})
    calls = engine.parse(text, TOOLS)

    runtime = ToolRuntime()

    @runtime.tool("echo")
    def echo(arguments, _metadata):
        return {"text": arguments["text"]}

    results = await runtime.execute(calls)
    print(results[0]["output"])


if __name__ == "__main__":
    asyncio.run(main())
