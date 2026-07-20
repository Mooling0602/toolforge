# ToolForge

给 **任意 LLM API** 补齐 / 统一 Function Calling 的中间件。

- 上游支持原生 tools → **透传**（Path A）
- 上游不支持 → **XYML 提示词注入 + 多格式解析**（Path B，引擎来自 `xyml-toolcall`）
- 客户端先走 **OpenAI Chat Completions**；Anthropic / Gemini 入口在后续版本
- **永不执行工具**——客户端执行后按标准协议回传结果即可

## 快速开始

```bash
cd toolforge
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -e ./vendor/xyml-toolcall
pip install -e ".[dev]"

cp config.example.yaml config.yaml
# 编辑 config.yaml：上游 base_url / api_key / native_fc

toolforge serve -c config.yaml
# 或
uvicorn toolforge.app:app --host 0.0.0.0 --port 8080
```

健康检查：`GET http://127.0.0.1:8080/healthz`

## 客户端用法（OpenAI SDK）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8080/v1",
    api_key="sk-toolforge-demo",  # 与 config.yaml allowed_keys 一致
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather by city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]

resp = client.chat.completions.create(
    model="demo-model",  # 需能路由到某个 upstream
    messages=[{"role": "user", "content": "Tokyo 天气？"}],
    tools=tools,
)
print(resp.choices[0].message.tool_calls)
```

单请求强制提示词 FC：

```http
X-ToolForge-FC-Mode: force_prompt
```

## 配置要点

| 字段 | 含义 |
|------|------|
| `upstreams[].native_fc` | `true` 时 auto 走原生透传；`false` 走提示词 FC |
| `features.fc_mode` | `auto` / `prefer_native` / `force_prompt` |
| `features.inject_protocol` | 默认 `XYML`（兼解析 QNML） |
| `client_authentication.allowed_keys` | 客户端 API Key |

`native_fc: false` 的典型上游：部分本地小模型、未暴露 tools 的 OpenAI 兼容网关、需要统一提示词协议的场景。  
也可把 [qwen2API](https://github.com/YuJunZhiXue/qwen2API) 指为上游：

```yaml
- name: qwen2api
  type: openai_compat
  base_url: "http://127.0.0.1:7860/v1"
  api_key: "your-key"
  models: ["*"]
  native_fc: false
  is_default: true
```

## 架构（简）

```
Client ──► ToolForge ──► Upstream LLM
             │
             ├─ Path A: tools 原样转发
             └─ Path B: 注入 XYML 指令 → 解析 tool_calls → 标准 OpenAI 响应
```

## 流式说明（v0.3 重点）

| 客户端协议 | 流式行为 |
|------------|----------|
| OpenAI Chat | 标准 `chat.completion.chunk` SSE + `[DONE]`；prompt FC 经 sieve，半包 marker 不泄漏 |
| OpenAI Responses | **真事件流**：`response.created` → `output_text.delta` / `function_call_arguments.delta` → `response.completed` |
| Anthropic | `message_start` / `content_block_*` / `message_stop`；上游 OpenAI 兼容时会桥接转换 |
| Gemini | native 透传 SSE；prompt FC 聚合后一帧返回完整 candidate |

SSE 解析使用完整帧状态机（支持多行 `data:`），异常时仍会发出终止帧，避免客户端挂死。

### 真上游 E2E

```bash
# 终端 1
cp config.example.yaml config.yaml   # 填入真实 upstream
toolforge serve -c config.yaml

# 终端 2
set TOOLFORGE_KEY=sk-toolforge-demo
set TOOLFORGE_MODEL=你的模型名
python examples/e2e_live.py --mode all
```

## 端点（v0.3）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/healthz` | 健康检查 |
| GET | `/metrics` | 简易请求计数 |
| GET | `/v1/models` | 聚合模型列表 |
| POST | `/v1/chat/completions` | OpenAI Chat |
| POST | `/v1/messages` | Anthropic Messages |
| POST | `/v1/messages/count_tokens` | token 估算 stub |
| POST | `/v1/responses` | OpenAI Responses |
| POST | `/v1beta/models/{model}:generateContent` | Gemini |
| POST | `/v1beta/models/{model}:streamGenerateContent` | Gemini 流 |

### 上游类型

| `upstreams[].type` | 说明 |
|--------------------|------|
| `openai_compat` | OpenAI / Grok / 任意兼容 `/v1/chat/completions` |
| `anthropic` | Anthropic Messages API |
| `gemini` | Google Gemini generateContent |

### Phase 2/3 能力

- **解析失败 / 截断重试**（`enable_fc_error_retry`）
- **CLI profiles + few-shot**（`enable_cli_profiles`，识别 Claude Code / Hermes / OpenClaw / OpenCode）
- **工具名混淆**（`obfuscate_tool_names`，Read→fs_open_file 等）
- **metrics**（`GET /metrics`）

## Docker

```bash
cp config.example.yaml config.yaml
docker compose up -d --build
```

## 开发测试

```bash
pip install -e ./vendor/xyml-toolcall
pip install -e ".[dev]"
pytest -q
```

## 与相关项目

| 项目 | 关系 |
|------|------|
| `xyml-toolcall`（vendored） | 解析 / 渲染 / 流式 sieve 引擎 |
| qwen2API | 可选上游；本仓库不依赖其 server 代码 |
| Toolify | 产品形态参考；实现为自研 MIT，未复制其代码 |

## License

MIT
