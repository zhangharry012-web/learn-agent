# Plan: 支持多 LLM Provider + base_url

## 方案概述

引入统一消息格式层（兼容层），让 `core.py` 与具体 LLM API 格式完全解耦。将单一 `llm.py` 拆分为 `llm/` 包，按职责分离模块。保留 `AnthropicLLM`（加 `base_url`），新增 `OpenAICompatibleLLM`（支持 OpenAI/DeepSeek/任意兼容 API）。通过工厂模式根据配置选择 provider。

## 目标文件结构

```
agent/
├── __init__.py
├── cli.py                   # 交互式 CLI（微调提示信息）
├── config.py                # 通用化配置（新增 provider/base_url）
├── core.py                  # Agent 主类（改用统一消息格式）
├── policy.py                # 不变
├── shell.py                 # 不变
├── tools.py                 # 不变
└── llm/                     # 【新】LLM 包，替代原 llm.py
    ├── __init__.py           # 导出公共接口 + 工厂函数 create_llm()
    ├── types.py              # 统一数据结构：ToolCall, ToolResult, LLMResponse
    ├── base.py               # BaseLLMClient 抽象基类
    ├── anthropic_client.py   # AnthropicLLM 实现（+ base_url）
    └── openai_client.py      # OpenAICompatibleLLM 实现（+ base_url）
```

## 架构设计

### 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  core.py (Agent)                                        │
│  只依赖统一类型: ToolCall, ToolResult, LLMResponse      │
│  通过 create_llm() 工厂获取客户端实例                     │
└─────────────────────┬───────────────────────────────────┘
                      │ generate(system_prompt, messages, tools)
                      │        ↕ 统一格式
                      ▼
┌─────────────────────────────────────────────────────────┐
│  llm/base.py :: BaseLLMClient                           │
│  抽象接口，定义 generate() 签名                           │
│  输入输出均为 llm/types.py 中的统一类型                    │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
           ▼                          ▼
┌────────────────────┐   ┌─────────────────────────┐
│  anthropic_client   │   │  openai_client           │
│                    │   │                         │
│  职责:             │   │  职责:                   │
│  1. 统一→Anthropic │   │  1. 统一→OpenAI 格式     │
│     格式转换       │   │     格式转换             │
│  2. 调用 API       │   │  2. 调用 API             │
│  3. Anthropic→统一 │   │  3. OpenAI→统一          │
│     响应解析       │   │     响应解析             │
│  4. 支持 base_url  │   │  4. 支持 base_url        │
└────────────────────┘   └─────────────────────────┘
```

### 数据流

```
用户输入
  │
  ▼
core.py 构建统一消息 ──→ [{role: "user", content: "..."}, ...]
  │
  ▼
create_llm(provider) 选择客户端
  │
  ├─ provider="anthropic" ──→ AnthropicLLM
  │     │ _to_anthropic_messages(): 统一格式 → content blocks
  │     │ _to_anthropic_tools(): input_schema → Anthropic tool schema
  │     │ API call → client.messages.create()
  │     │ _parse_response(): content blocks → LLMResponse
  │     ▼
  │
  ├─ provider="openai"|"deepseek"|... ──→ OpenAICompatibleLLM
  │     │ _to_openai_messages(): 统一格式 → OpenAI messages
  │     │ _to_openai_tools(): input_schema → function calling schema
  │     │ API call → client.chat.completions.create()
  │     │ _parse_response(): choices → LLMResponse
  │     ▼
  │
  ▼
LLMResponse(text, tool_calls, stop_reason) ──→ core.py 统一处理
```

## 模块设计

### `llm/types.py` — 统一数据结构

定义三个核心 dataclass，作为整个系统的通用语言：

- **`ToolCall`**: `{id, name, arguments}` — 统一的工具调用请求
- **`ToolResult`**: `{tool_call_id, content, is_error}` — 统一的工具执行结果
- **`LLMResponse`**: `{text, tool_calls, stop_reason}` — 统一的模型响应

`core.py` 中的消息列表使用统一的 dict 格式：
- `{"role": "user", "content": "..."}` — 用户消息
- `{"role": "assistant", "text": "...", "tool_calls": [ToolCall...]}` — 助手消息
- `{"role": "tool_result", "results": [ToolResult...]}` — 工具结果

### `llm/base.py` — 抽象基类

`BaseLLMClient` 定义 `generate()` 接口签名，输入输出均为统一类型。所有 provider 实现类必须继承此基类。

### `llm/anthropic_client.py` — Anthropic 实现

职责：
1. 构造 `anthropic.Anthropic` 客户端（支持可选 `base_url`）
2. **入方向转换**：统一消息 → Anthropic content blocks（`tool_use`/`tool_result`）
3. **出方向转换**：Anthropic 响应 → `LLMResponse`
4. tool schema 转换：当前 `tools.py` 输出的 `definition()` 已是 Anthropic 格式（`name`/`description`/`input_schema`），可直接透传

关键转换点：
- Anthropic 的 `tool_result` 必须放在 `role: "user"` 的 content blocks 中
- Anthropic 的 `system` 是独立参数，不在 messages 中

### `llm/openai_client.py` — OpenAI 兼容实现

职责：
1. 构造 `openai.OpenAI` 客户端（支持 `base_url`，实现 DeepSeek 等兼容 API 接入）
2. **入方向转换**：统一消息 → OpenAI messages（`tool_calls`/`role: "tool"`）
3. **出方向转换**：OpenAI `choices[0].message` → `LLMResponse`
4. tool schema 转换：`input_schema` → OpenAI `function.parameters`

关键转换点：
- OpenAI 的 `system` 是 `{"role": "system", "content": "..."}` 消息
- OpenAI 的 tool 结果用独立的 `{"role": "tool", "tool_call_id": "..."}` 消息
- OpenAI 的 `tool_calls` 中 `arguments` 是 JSON 字符串，需要 `json.dumps`/`json.loads`

### `llm/__init__.py` — 公共导出 + 工厂

导出所有公共类型，提供 `create_llm()` 工厂函数：
- 根据 `provider` 参数分发到对应实现类
- 支持的 provider：`"anthropic"` / `"openai"` / `"deepseek"` / `"openai-compatible"`
- 未知 provider 抛出 `ValueError`

### `config.py` — 通用化配置

新增字段：
- `llm_provider`: 从 `LLM_PROVIDER` 环境变量，默认 `"anthropic"`
- `llm_api_key`: 从 `LLM_API_KEY`，fallback 到 `ANTHROPIC_API_KEY`
- `llm_model`: 从 `LLM_MODEL`，fallback 到 `ANTHROPIC_MODEL`
- `llm_base_url`: 从 `LLM_BASE_URL`，默认空（使用 SDK 默认地址）

环境变量优先级：`LLM_*` > `ANTHROPIC_*` > 默认值

保留 `anthropic_api_key`/`anthropic_model` 属性做向后兼容。

### `core.py` — 适配统一格式

改动范围：
1. `_build_default_llm()` → 调用 `create_llm()` 工厂，传入 config 中的 provider/key/model/base_url
2. `_run_llm_loop()` → 构建和消费统一格式的消息（不再直接操作 Anthropic content blocks）
3. `_handle_approval()` → 使用 `ToolResult` 构建工具结果消息

**核心原则**：`core.py` 中不出现任何 Anthropic 或 OpenAI 特有的数据结构。

### `cli.py` — 微调

启动提示改为显示当前 provider 和 model 信息。

## 依赖变化

```
# requirements.txt
anthropic>=0.39.0
openai>=1.0.0       # 新增
```

`openai` SDK 是轻量依赖，且是 OpenAI 兼容 API 的事实标准客户端。

## 使用方式

| 场景 | 环境变量 |
|------|----------|
| Anthropic（默认不变） | `ANTHROPIC_API_KEY` |
| Anthropic + 代理 | `LLM_API_KEY` + `LLM_BASE_URL` |
| OpenAI | `LLM_PROVIDER=openai` + `LLM_API_KEY` + `LLM_MODEL=gpt-4o` |
| DeepSeek | `LLM_PROVIDER=deepseek` + `LLM_API_KEY` + `LLM_MODEL=deepseek-chat` + `LLM_BASE_URL=https://api.deepseek.com` |
| 任意兼容 API | `LLM_PROVIDER=openai-compatible` + `LLM_API_KEY` + `LLM_MODEL` + `LLM_BASE_URL` |

## 不变的部分

- `agent/policy.py` — 安全策略，不涉及 LLM
- `agent/shell.py` — 子进程执行，不涉及 LLM
- `agent/tools.py` — 工具定义和执行逻辑不变，tool schema 格式转换在各 LLM 客户端内部处理

## 扩展性

新增 provider 只需：
1. 在 `llm/` 下新增 `xxx_client.py`，继承 `BaseLLMClient`
2. 实现 `generate()` 及内部格式转换
3. 在 `llm/__init__.py` 的 `create_llm()` 中注册

## TODO

- [ ] 1. 创建 `agent/llm/` 包结构（`types.py`, `base.py`, `__init__.py`）
- [ ] 2. 迁移 `AnthropicLLM` 到 `llm/anthropic_client.py`，添加 base_url + 格式转换
- [ ] 3. 新增 `llm/openai_client.py`（OpenAICompatibleLLM）
- [ ] 4. 实现 `llm/__init__.py` 工厂函数
- [ ] 5. 更新 `agent/config.py` 通用化配置
- [ ] 6. 更新 `agent/core.py` 适配统一消息格式
- [ ] 7. 更新 `agent/cli.py` 提示信息
- [ ] 8. 删除旧 `agent/llm.py`
- [ ] 9. 更新 `requirements.txt`
- [ ] 10. 更新 `tests/test_agent.py` 适配 + 新增测试
- [ ] 11. 运行测试确保全部通过
