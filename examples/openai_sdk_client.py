"""Minimal OpenAI SDK client against a local ToolForge instance."""

from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="sk-toolforge-demo")

tools = [
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

completion = client.chat.completions.create(
    model="demo-model",
    messages=[{"role": "user", "content": "What is the weather in Tokyo?"}],
    tools=tools,
)

message = completion.choices[0].message
print("finish:", completion.choices[0].finish_reason)
print("content:", message.content)
print("tool_calls:", message.tool_calls)
