# ToolForge

**只做一件事：给任意 LLM API 补齐 / 统一工具调用（Function Calling）。**

中间件夹在客户端和上游模型之间：

| 路径 | 条件 | 行为 |
|------|------|------|
| **A 原生透传** | 上游 `native_fc: true` | 原样转发 `tools` / `tool_calls` |
| **B 提示词 FC** | 上游 `native_fc: false` 或强制 prompt | 注入 XYML 协议 → 解析模型文本 → 输出标准 `tool_calls` / `tool_use` / `functionCall` |

- **不执行工具**（客户端执行后把结果按协议回传即可）
- **流式 / 非流式**均支持
- 客户端协议：OpenAI Chat · OpenAI Responses · Anthropic Messages · Gemini

```text
Client SDK  ──►  ToolForge  ──►  任意上游 LLM
   tools            │              (有/无原生 FC)
                    ├─ Path A 透传
                    └─ Path B XYML 注入 + 解析
```

---

## Docker 部署（推荐）

```bash
git clone https://github.com/YuJunZhiXue/toolforge.git
cd toolforge

# 开箱即用（默认挂载 config.example.yaml）
docker compose up -d --build
curl http://127.0.0.1:8080/healthz
```

自定义配置：

```bash
cp config.example.yaml config.yaml
# 编辑 base_url / api_key / native_fc / allowed_keys
HOST_CONFIG=./config.yaml docker compose up -d --build
```

默认端口 **8080**。改端口：`HOST_PORT=9000 docker compose up -d`

上游在宿主机时（Docker Desktop），`base_url` 示例：

```yaml
base_url: "http://host.docker.internal:7860/v1"
```

密钥可用环境变量注入（对应配置里的 `${OPENAI_API_KEY}` 等）：

```bash
OPENAI_API_KEY=sk-xxx HOST_CONFIG=./config.yaml docker compose up -d
```

---

## 本地运行（不经过 Docker）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -e ./vendor/xyml-toolcall
pip install -e .

cp config.example.yaml config.yaml
toolforge serve -c config.yaml
# 或: uvicorn toolforge.app:app --host 0.0.0.0 --port 8080
```

---

## 客户端怎么用

把任意 OpenAI 兼容 SDK 的 `base_url` 指到 ToolForge：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8080/v1",
    api_key="sk-toolforge-demo",  # = config.yaml client_authentication.allowed_keys
)

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "按城市查天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

# 非流式
r = client.chat.completions.create(
    model="your-model",
    messages=[{"role": "user", "content": "东京天气？"}],
    tools=tools,
)
print(r.choices[0].message.tool_calls)

# 流式
stream = client.chat.completions.create(
    model="your-model",
    messages=[{"role": "user", "content": "东京天气？"}],
    tools=tools,
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta)
```

单请求强制走提示词 FC（忽略上游 native）：

```http
X-ToolForge-FC-Mode: force_prompt
```

Anthropic / Gemini 客户端同理，把地址指到本服务对应路径即可。

---

## 配置说明

### 上游 `upstreams[]`

| 字段 | 说明 |
|------|------|
| `type` | `openai_compat` · `anthropic` · `gemini` |
| `base_url` | 上游 API 根地址 |
| `api_key` | 上游密钥，支持 `${ENV}` |
| `models` | 模型名列表；`["*"]` 接所有未命中模型 |
| `native_fc` | `true` 透传原生 tools；`false` 走 XYML 提示词解析 |
| `is_default` | 默认上游 |

### 功能 `features`

| 字段 | 默认 | 说明 |
|------|------|------|
| `fc_mode` | `auto` | `auto` / `prefer_native` / `force_prompt` |
| `enable_streaming` | `true` | 是否允许 `stream: true` |
| `enable_fc_error_retry` | `true` | 解析失败 / 截断时重试 |
| `inject_protocol` | `XYML` | 提示词协议（解析仍兼容 QNML 等） |
| `enable_cli_profiles` | `true` | Claude Code / Hermes 等工具名画像 |
| `obfuscate_tool_names` | `false` | `Read`→`fs_open_file` 等名称混淆 |
| `strip_think_tags` | `true` | 忽略 `<think>` 内伪 tool 文本 |

### 鉴权

```yaml
client_authentication:
  enabled: true
  allowed_keys: ["sk-toolforge-demo"]
```

客户端用 `Authorization: Bearer <key>` 或 `x-api-key`。

---

## HTTP 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/healthz` | 健康检查 |
| GET | `/metrics` | 简易计数 |
| GET | `/v1/models` | 聚合上游模型 |
| POST | `/v1/chat/completions` | OpenAI Chat（流式/非流式） |
| POST | `/v1/responses` | OpenAI Responses（含真 SSE 事件流） |
| POST | `/v1/messages` | Anthropic Messages |
| POST | `/v1/messages/count_tokens` | token 估算 |
| POST | `/v1beta/models/{model}:generateContent` | Gemini |
| POST | `/v1beta/models/{model}:streamGenerateContent` | Gemini 流 |

---

## 流式行为（工具调用相关）

| 协议 | 流式输出 |
|------|----------|
| OpenAI Chat | `chat.completion.chunk` + `tool_calls` delta + `[DONE]` |
| OpenAI Responses | `response.created` → text/function_call deltas → `response.completed` |
| Anthropic | `content_block_*` / `tool_use` 事件 |
| Gemini | native SSE 透传；prompt FC 时聚合后返回完整 `functionCall` |

SSE 使用完整帧解析（多行 `data:`），异常也会发终止帧，避免客户端挂死。

---

## 目录（仅工具调用）

```text
toolforge/
├── config.example.yaml     # 配置模板
├── docker-compose.yml
├── Dockerfile
├── src/toolforge/          # 中间件本体
│   ├── app.py              # 路由入口
│   ├── config.py / auth.py
│   ├── fc/                 # 策略 · 注入 · 解析 · 恢复 · profile
│   ├── engine/             # 编排 · 上游 wire
│   ├── protocols/          # OpenAI / Anthropic / Gemini / Responses
│   ├── stream/             # Chat SSE · Responses SSE
│   ├── upstream/           # 上游 HTTP 客户端
│   ├── convert.py          # 协议互转
│   └── models/             # 中立 Canonical 模型
├── vendor/xyml-toolcall/   # 内嵌解析引擎（XYML/QNML/XML/JSON）
├── tests/                  # 单元 / 流式合同测试
└── examples/e2e_live.py    # 真上游联调脚本（可选）
```

---

## 测试

```bash
pip install -e ./vendor/xyml-toolcall
pip install -e ".[dev]"
pytest -q
```

真上游（服务已启动）：

```bash
set TOOLFORGE_KEY=sk-toolforge-demo
set TOOLFORGE_MODEL=your-model
python examples/e2e_live.py --mode chat-stream
```

---

## License

MIT
