# Plan: 支持多 LLM Provider + base_url

## 概述

将单一 `llm.py` 拆分为 `llm/` 包，引入统一消息格式兼容层，让上层 `core.py` 与具体 LLM API 格式完全解耦。保留 Anthropic 支持并加 `base_url`，新增 OpenAI 兼容客户端支持 DeepSeek 等任意兼容 API。通过工厂模式根据配置选择 provider。

## 目标文件结构

```
agent/
├── __init__.py
├── cli.py                   # 微调：启动提示显示 provider 和 model
├── config.py                # 通用化配置（新增 provider/base_url 字段）
├── core.py                  # 改用统一消息格式，不再依赖 Anthropic 特有结构
├── policy.py                # 不变
├── shell.py                 # 不变
├── tools.py                 # 不变
└── llm/                     # 【新】LLM 包，替代原 llm.py
    ├── __init__.py           # 导出公共接口 + create_llm() 工厂
    ├── types.py              # 统一数据结构定义
    ├── base.py               # BaseLLMClient 抽象基类
    ├── anthropic_client.py   # Anthropic 实现（+ base_url + 格式转换）
    └── openai_client.py      # OpenAI 兼容实现（+ base_url + 格式转换）
```

## 分层架构

```
┌──────────────────────────────────────────────────┐
│  core.py (Agent)                                  │
│  只依赖: ToolCall, ToolResult, LLMResponse        │
│  通过 create_llm() 获取客户端                      │
└───────────────────┬──────────────────────────────┘
                    │ generate(system_prompt, messages, tools)
                    │       ↕ 统一格式
                    ▼
┌──────────────────────────────────────────────────┐
│  llm/base.py :: BaseLLMClient                     │
│  抽象接口，输入输出均为 types.py 中的统一类型       │
└─────────┬────────────────────────┬───────────────┘
          │                        │
          ▼                        ▼
┌───────────────────┐   ┌────────────────────────┐
│ anthropic_client   │   │ openai_client           │
│                   │   │                        │
│ 统一 ↔ Anthropic  │   │ 统一 ↔ OpenAI          │
│ content blocks    │   │ messages/tool_calls    │
│ + base_url        │   │ + base_url             │
└───────────────────┘   └────────────────────────┘
```

## 数据流

```
用户输入
  │
  ▼
core.py 构建统一消息
  │  [{role: "user", content: "..."},
  │   {role: "assistant", text: "...", tool_calls: [ToolCall...]},
  │   {role: "tool_result", results: [ToolResult...]}]
  │
  ▼
create_llm(provider) ─── 选择客户端
  │
  ├─ "anthropic" ──→ AnthropicLLM
  │   _to_anthropic_messages()   # 统一 → content blocks
  │   _to_anthropic_tools()      # input_schema 直接透传
  │   client.messages.create()   # system 作为独立参数
  │   _parse_response()          # content blocks → LLMResponse
  │
  ├─ "openai"|"deepseek"|... ──→ OpenAICompatibleLLM
  │   _to_openai_messages()      # 统一 → OpenAI messages, system 插入消息列表
  │   _to_openai_tools()         # input_schema → function.parameters
  │   client.chat.completions.create()
  │   _parse_response()          # choices[0].message → LLMResponse
  │
  ▼
LLMResponse(text, tool_calls, stop_reason) → core.py 统一处理
```

## 模块设计

### `llm/types.py` — 统一数据结构

定义三个核心 dataclass，作为系统各层之间的通用语言：

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool

@dataclass
class LLMResponse:
    text: str                    # 文本回复（可为空）
    tool_calls: List[ToolCall]   # 工具调用列表（可为空）
    stop_reason: str             # "end_turn" / "tool_use"
```

`core.py` 中的消息列表使用统一 dict 格式：

| role | 结构 | 说明 |
|------|------|------|
| `"user"` | `{role, content: str}` | 用户消息 |
| `"assistant"` | `{role, text: str, tool_calls: List[ToolCall]}` | 助手消息 |
| `"tool_result"` | `{role, results: List[ToolResult]}` | 工具执行结果 |

### `llm/base.py` — 抽象基类

```python
class BaseLLMClient:
    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError
```

所有 provider 必须继承此基类，实现 `generate()`。

同时保留 `extract_text()` 辅助函数，改为从 `LLMResponse.text` 直接提取。

### `llm/anthropic_client.py` — Anthropic 实现

**构造函数**：接收 `api_key, model, max_tokens, base_url`，创建 `anthropic.Anthropic` 客户端。`base_url` 可选，为空时使用 SDK 默认地址。

**格式转换职责**（内部私有方法）：

| 方法 | 方向 | 关键转换点 |
|------|------|-----------|
| `_to_anthropic_messages()` | 统一 → Anthropic | `assistant` 重建 content blocks（text + tool_use）；`tool_result` 放入 `role: "user"` 下 |
| `_to_anthropic_tools()` | 统一 → Anthropic | 当前 `tools.py` 的 `definition()` 输出已兼容，直接透传 |
| `_parse_response()` | Anthropic → 统一 | 遍历 content blocks，text → `LLMResponse.text`，tool_use → `ToolCall` |

### `llm/openai_client.py` — OpenAI 兼容实现

**构造函数**：接收 `api_key, model, max_tokens, base_url`，创建 `openai.OpenAI` 客户端。通过 `base_url` 支持 DeepSeek 等任意兼容 API。

**格式转换职责**（内部私有方法）：

| 方法 | 方向 | 关键转换点 |
|------|------|-----------|
| `_to_openai_messages()` | 统一 → OpenAI | `system_prompt` 插入为 `{role: "system"}` 消息；`tool_calls` 中 `arguments` 需 `json.dumps`；`tool_result` 拆为多条 `{role: "tool"}` 消息 |
| `_to_openai_tools()` | 统一 → OpenAI | `input_schema` → `function.parameters`，外包 `{type: "function", function: {...}}` |
| `_parse_response()` | OpenAI → 统一 | `choices[0].message` 解析；`tool_calls[].function.arguments` 需 `json.loads` |

### `llm/__init__.py` — 公共导出 + 工厂

导出所有公共类型（`ToolCall`, `ToolResult`, `LLMResponse`, `BaseLLMClient`, `extract_text`），提供工厂函数：

```python
def create_llm(*, provider, api_key, model, max_tokens=1024, base_url="") -> BaseLLMClient:
    # provider -> 对应实现类的映射
    # "anthropic" -> AnthropicLLM
    # "openai" / "deepseek" / "openai-compatible" -> OpenAICompatibleLLM
    # 未知 provider -> raise ValueError
```

### `config.py` — 通用化配置

新增字段及环境变量映射：

| 字段 | 环境变量 | Fallback | 默认值 |
|------|----------|----------|--------|
| `llm_provider` | `LLM_PROVIDER` | — | `"anthropic"` |
| `llm_api_key` | `LLM_API_KEY` | `ANTHROPIC_API_KEY` | `""` |
| `llm_model` | `LLM_MODEL` | `ANTHROPIC_MODEL` | `"claude-sonnet-4-20250514"` |
| `llm_base_url` | `LLM_BASE_URL` | — | `""` |

保留 `anthropic_api_key` / `anthropic_model` 属性做向后兼容（委托到通用字段）。

`llm_enabled` 判断逻辑不变：`bool(llm_api_key)`。

### `core.py` — 适配统一格式

改动范围：

1. **`_build_default_llm()`** — 调用 `create_llm()` 工厂，传入 config 的 provider/key/model/base_url
2. **`_run_llm_loop()`** — 构建和消费统一格式消息。核心变化：
   - 从 `response` 提取 `ToolCall` 列表（而非遍历 content blocks）
   - 构建 `assistant_message` 为统一 dict 格式
   - 构建 `tool_result` 消息使用 `ToolResult` dataclass
3. **`_handle_approval()`** — 工具结果构建改用 `ToolResult`
4. **import** — 从 `agent.llm` 导入统一类型

**核心原则**：`core.py` 中不出现任何 Anthropic 或 OpenAI 特有的数据结构。

### `cli.py` — 微调

启动提示从 `"ANTHROPIC_API_KEY not found"` 改为 `"LLM_API_KEY not found"`，并显示当前 provider 和 model。

## 依赖变化

```
# requirements.txt
anthropic>=0.39.0
openai>=1.0.0       # 新增
```

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 统一格式定义位置 | 独立 `types.py` | 避免循环导入，各模块均可引用 |
| 工厂函数位置 | `llm/__init__.py` | 对外只需 `from agent.llm import create_llm` |
| tool schema 转换位置 | 各 client 内部 | `tools.py` 不需要感知 provider 差异 |
| base_url 为空时行为 | 不传给 SDK | SDK 自动使用官方默认地址 |
| 向后兼容策略 | `ANTHROPIC_*` 作为 fallback | 现有用户无需改任何配置 |

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
- `agent/tools.py` — 工具定义和执行逻辑不变，schema 格式转换在各 client 内部

## 扩展性

新增 provider 只需：
1. 在 `llm/` 下新增 `xxx_client.py`，继承 `BaseLLMClient`
2. 实现 `generate()` 及内部格式转换
3. 在 `llm/__init__.py` 的 `create_llm()` 中注册

## TODO

- [ ] 1. 创建 `agent/llm/` 包结构（`__init__.py`, `types.py`, `base.py`）
- [ ] 2. 迁移 `AnthropicLLM` 到 `llm/anthropic_client.py`，添加 base_url + 格式转换
- [ ] 3. 新增 `llm/openai_client.py`（OpenAICompatibleLLM）
- [ ] 4. 实现 `llm/__init__.py` 公共导出 + 工厂函数
- [ ] 5. 更新 `agent/config.py` 通用化配置
- [ ] 6. 更新 `agent/core.py` 适配统一消息格式
- [ ] 7. 更新 `agent/cli.py` 提示信息
- [ ] 8. 删除旧 `agent/llm.py`
- [ ] 9. 更新 `requirements.txt`
- [ ] 10. 更新 `tests/test_agent.py` 适配 + 新增测试
- [ ] 11. 运行测试确保全部通过
