# Plan: 支持多 LLM Provider + base_url

## 概述

将单一 `llm.py` 拆分为 `llm/` 包，引入统一消息格式兼容层，让上层 `core.py` 与具体 LLM API 格式完全解耦。保留 Anthropic 支持并加 `base_url`，新增 OpenAI 兼容客户端支持 DeepSeek 等任意兼容 API。通过工厂模式根据配置选择 provider。

本轮仅更新方案文档，不开始实现。重点补齐统一消息格式约束、停止原因标准化、错误处理策略、`base_url` 约定、CLI 提示语义、配置优先级、测试验收标准和 TODO 对齐关系，确保计划进入可实施状态。

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
    stop_reason: str             # 标准化后的停止原因
```

`core.py` 中的消息列表使用统一 dict 格式：

| role | 结构 | 说明 |
|------|------|------|
| `"user"` | `{role, content: str}` | 用户消息 |
| `"assistant"` | `{role, text: str, tool_calls: List[ToolCall]}` | 助手消息 |
| `"tool_result"` | `{role, results: List[ToolResult]}` | 工具执行结果 |

#### 统一消息格式不变量

为避免 provider 间转换歧义，统一层增加如下严格约束：

1. `assistant` 消息允许同时包含 `text` 和 `tool_calls`。也就是说，一轮回复可以既输出自然语言，也发起工具调用。
2. `assistant.tool_calls` 允许为空；为空时表示本轮没有工具调用。
3. `tool_result` 只能出现在某条包含 `tool_calls` 的 `assistant` 消息之后，不能独立出现。
4. 单条 `tool_result` 消息承载同一轮 assistant 发起的一个或多个工具执行结果。
5. `ToolResult.tool_call_id` 必须与上一轮 assistant 中的某个 `ToolCall.id` 一一对应；不允许出现找不到上游调用的孤立结果。
6. `tool_result.results` 不允许为部分未知集合；如果上层选择分批回填结果，必须保证每个结果都带有明确 `tool_call_id`，并由转换层原样保留。
7. 统一层不保存 provider 原生 block/message 结构，避免 `core.py` 再次泄漏下层协议细节。

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

**停止原因标准化**：

- Anthropic 原生 `stop_reason` 在 provider 层做标准化后写入 `LLMResponse.stop_reason`
- 计划中的标准化目标值为：`end_turn`、`tool_use`、`max_tokens`、`other`
- 未识别值不在 `core.py` 中特殊处理，但会落到 `other`

### `llm/openai_client.py` — OpenAI 兼容实现

**构造函数**：接收 `api_key, model, max_tokens, base_url`，创建 `openai.OpenAI` 客户端。通过 `base_url` 支持 DeepSeek 等任意兼容 API。

**格式转换职责**（内部私有方法）：

| 方法 | 方向 | 关键转换点 |
|------|------|-----------|
| `_to_openai_messages()` | 统一 → OpenAI | `system_prompt` 插入为 `{role: "system"}` 消息；`tool_calls` 中 `arguments` 需 `json.dumps`；`tool_result` 拆为多条 `{role: "tool"}` 消息 |
| `_to_openai_tools()` | 统一 → OpenAI | `input_schema` → `function.parameters`，外包 `{type: "function", function: {...}}` |
| `_parse_response()` | OpenAI → 统一 | `choices[0].message` 解析；`tool_calls[].function.arguments` 需 `json.loads` |

**停止原因标准化**：

- OpenAI-compatible 的 `finish_reason` 统一映射到 `LLMResponse.stop_reason`
- 建议映射：
  - `stop` → `end_turn`
  - `tool_calls` → `tool_use`
  - `length` → `max_tokens`
  - 其它未知值 → `other`

**工具参数解析失败策略**：

OpenAI-compatible 返回的 `tool_calls[].function.arguments` 需要 `json.loads`。这里必须定义受控失败策略，避免 provider 返回异常 JSON 时直接把系统拖垮。

约定如下：

1. provider 层尝试对 `arguments` 做 `json.loads`
2. 若返回空字符串、非法 JSON、`null` 或非对象结构，视为协议错误
3. provider 层抛出受控异常，例如 `ValueError("Invalid tool arguments from provider")`
4. 上层不做静默兜底成 `{}`，避免执行错误工具参数
5. 如需调试，可在异常信息或日志中保留原始 arguments 字符串，但不改变统一接口结构

### `llm/__init__.py` — 公共导出 + 工厂

导出所有公共类型（`ToolCall`, `ToolResult`, `LLMResponse`, `BaseLLMClient`, `extract_text`），提供工厂函数：

```python
def create_llm(*, provider, api_key, model, max_tokens=1024, base_url="") -> BaseLLMClient:
    # provider -> 对应实现类的映射
    # "anthropic" -> AnthropicLLM
    # "openai" / "deepseek" / "openai-compatible" -> OpenAICompatibleLLM
    # 未知 provider -> raise ValueError
```

#### provider 命名与别名规则

为避免实现阶段临场判断，本计划固定以下映射规则：

- `anthropic` → `AnthropicLLM`
- `openai` → `OpenAICompatibleLLM`
- `deepseek` → `OpenAICompatibleLLM`
- `openai-compatible` → `OpenAICompatibleLLM`
- 未知 provider 值一律 `raise ValueError`

不在本轮计划中引入更宽松的大小写归一化、模糊匹配或自动猜测 provider 逻辑；调用方需提供合法 provider 名称。

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

#### 配置优先级规则

为了满足实现期可预期性，配置读取优先级固定如下：

1. `llm_provider` 只读取 `LLM_PROVIDER`，默认值为 `anthropic`
2. `llm_api_key` 优先读取 `LLM_API_KEY`；当其为空时，再 fallback 到 `ANTHROPIC_API_KEY`
3. `llm_model` 优先读取 `LLM_MODEL`；当其为空时，再 fallback 到 `ANTHROPIC_MODEL`
4. `llm_base_url` 只读取 `LLM_BASE_URL`，为空表示未配置
5. 不新增 provider-specific 的 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 等分叉环境变量，避免配置面继续膨胀

### `core.py` — 适配统一格式

改动范围：

1. **`_build_default_llm()`** — 调用 `create_llm()` 工厂，传入 config 的 provider/key/model/base_url
2. **`_run_llm_loop()`** — 构建和消费统一格式消息。核心变化：
   - 从 `response` 提取 `ToolCall` 列表（而非遍历 content blocks）
   - 构建 `assistant_message` 为统一 dict 格式
   - 构建 `tool_result` 消息使用 `ToolResult` dataclass
   - 仅依赖 `LLMResponse.stop_reason` 的标准化结果，不依赖 provider 原生字段
3. **`_handle_approval()`** — 工具结果构建改用 `ToolResult`
4. **import** — 从 `agent.llm` 导入统一类型

**核心原则**：`core.py` 中不出现任何 Anthropic 或 OpenAI 特有的数据结构。

### `cli.py` — 微调

CLI 提示文案不再绑定 Anthropic 专有环境变量。调整为更中性的提示语义：

- 缺失凭据时提示 `No LLM credentials configured`
- 文案层面说明会检查 `LLM_API_KEY` 和兼容 fallback 环境变量
- 启动时显示当前 `provider`、`model` 和是否设置 `base_url`
- 不打印 API key，不完整回显敏感 endpoint 参数

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
| 停止原因统一层策略 | provider 内标准化 | 避免 `core.py` 感知底层 finish reason 细节 |
| tool arguments 解析失败策略 | 显式抛错，不静默兜底 | 防止错误参数被继续执行 |
| provider alias 范围 | 仅支持计划中显式列出的别名 | 避免自动猜测带来不确定性 |
| 配置面控制 | 不引入更多 provider-specific env | 防止配置复杂度失控 |

## `base_url` 兼容策略

为减少魔法行为，`base_url` 约定如下：

1. 代码层不主动补全或规范化 `base_url`
2. 用户需提供 provider 可接受的完整 endpoint
3. 对于某些 OpenAI-compatible 服务，是否需要 `/v1` 由用户配置决定，代码只做原样透传
4. `base_url` 为空时，不向 SDK 传该参数
5. Anthropic 路径在实现阶段需验证当前依赖版本是否稳定支持 `base_url`；若 SDK 版本行为不一致，需要在实现时补充兼容处理，但不改变本计划的抽象层设计

## 错误处理策略

### 统一层约束

- 若 provider 返回空文本且无工具调用，允许生成空 `LLMResponse.text`，但必须保留可识别的 `stop_reason`
- 若 provider 返回未知停止原因，标准化为 `other`
- 若 provider 返回非法工具调用参数，必须显式报错，不执行工具
- 若 provider 返回的工具结果无法与 `ToolCall.id` 对应，视为协议不一致错误

### provider 侧职责

- provider 负责把原生响应尽可能收敛成统一结构
- provider 负责在协议异常处尽早失败，而不是把脏数据传给 `core.py`
- `core.py` 只消费合法的统一结构，不承担底层协议纠错职责

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

## 测试计划

本次变更属于“协议转换 + 配置泛化 + provider 抽象”重构，测试必须覆盖转换正确性和 Anthropic 回归行为。

### 单元测试覆盖点

| 测试类型 | 覆盖内容 |
|---|---|
| 配置测试 | `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL` 与 `ANTHROPIC_*` fallback 的解析行为 |
| 工厂测试 | 不同 provider 名称映射到正确 client，未知 provider 抛 `ValueError` |
| Anthropic 转换测试 | 统一消息 → Anthropic messages/tools；Anthropic response → `LLMResponse` |
| OpenAI 转换测试 | 统一消息 → OpenAI messages/tools；OpenAI response → `LLMResponse` |
| 错误处理测试 | 非法 tool arguments、未知 stop reason、无效 tool_call_id 触发受控失败 |
| Core 回归测试 | `core.py` 在 Anthropic 路径下的工具调用循环行为保持兼容 |

### 最低测试交付要求

进入实现后，至少需要补齐以下可执行测试项：

1. 配置优先级测试：验证 `LLM_API_KEY` 覆盖 `ANTHROPIC_API_KEY`
2. 配置回退测试：仅设置 `ANTHROPIC_API_KEY` 仍能启用默认 provider
3. 工厂映射测试：验证 `anthropic`、`openai`、`deepseek`、`openai-compatible` 的映射结果
4. 未知 provider 测试：传入非法 provider 时抛 `ValueError`
5. OpenAI 参数解析失败测试：非法 JSON 参数触发受控异常
6. 停止原因标准化测试：Anthropic/OpenAI 两条路径都能映射到统一值
7. Core 回归测试：Anthropic 原有工具调用 loop 的行为结果不变

### 回归重点

1. 老配置仅设置 `ANTHROPIC_API_KEY` 时，仍能正常初始化默认 LLM
2. `core.py` 中不再出现 provider-specific block 结构判断
3. 工具调用链在 Anthropic 与 OpenAI-compatible 下都能产出统一 `LLMResponse`
4. 新增 provider 不需要修改 `tools.py`
5. 默认 Anthropic 路径的对外行为保持兼容，不要求用户修改现有配置

## 验收标准

满足以下条件后，计划才允许进入实现阶段：

1. `plan.md` 中的统一消息格式、停止原因和错误处理策略已经定稿
2. `base_url` 的透传边界与不做自动规范化的约定已明确
3. `config.py` 的向后兼容方案已明确，不会破坏现有 Anthropic 用户
4. provider 别名范围与配置优先级规则已明确，不依赖实现阶段临时决定
5. 测试清单已覆盖配置、转换、工厂和核心回归路径
6. 最低测试交付要求已经列成可执行项，而不是抽象原则
7. 团队确认 CLI 提示文案采用中性表述，不泄露敏感信息
8. 团队接受本轮不引入 LiteLLM，也不继续扩展更多 provider-specific 环境变量

## TODO

- [x] 1. 创建 `agent/llm/` 包结构（`__init__.py`, `types.py`, `base.py`）
- [x] 2. 迁移 `AnthropicLLM` 到 `llm/anthropic_client.py`，添加 base_url + 格式转换
- [x] 3. 新增 `llm/openai_client.py`（OpenAICompatibleLLM）
- [x] 4. 实现 `llm/__init__.py` 公共导出 + 工厂函数
- [x] 5. 固化 provider 别名规则与未知 provider 报错行为
- [x] 6. 更新 `agent/config.py` 通用化配置
- [x] 7. 固化 `LLM_*` 与 `ANTHROPIC_*` fallback 的优先级逻辑
- [x] 8. 更新 `agent/core.py` 适配统一消息格式
- [x] 9. 更新 `agent/cli.py` 提示信息
- [x] 10. 删除旧 `agent/llm.py`
- [x] 11. 更新 `requirements.txt`
- [x] 12. 更新 `tests/test_agent.py` 适配 + 新增测试
- [x] 13. 补充配置优先级、工厂映射、provider 转换与错误处理测试用例
- [x] 14. 运行测试确保全部通过
- [x] 15. 验证 Anthropic SDK 在当前依赖版本下的 `base_url` 行为
- [x] 16. 对照验收标准做一次实现前自检
