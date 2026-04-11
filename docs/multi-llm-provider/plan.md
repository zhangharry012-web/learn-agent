# Plan: 支持多 LLM Provider + base_url

## 方案概述

引入统一消息格式层，让 `core.py` 与具体 LLM API 格式解耦。保留 `AnthropicLLM`（加 `base_url`），新增 `OpenAICompatibleLLM`（支持 OpenAI/DeepSeek/任意兼容 API）。通过工厂模式根据配置选择 provider。

## 架构设计

```
┌──────────────────────────────────────────────┐
│  core.py（Agent）                             │
│  只操作统一格式: UnifiedMessage, ToolCall     │
└──────────────┬───────────────────────────────┘
               │ generate(统一格式)
               ▼
┌──────────────────────────────────────────────┐
│  BaseLLMClient                               │
│  接口: generate(system_prompt, messages,      │
│         tools) -> LLMResponse                │
│  内部消息/工具格式已统一                       │
└──────┬────────────────────┬──────────────────┘
       │                    │
       ▼                    ▼
┌─────────────┐   ┌──────────────────────┐
│AnthropicLLM │   │OpenAICompatibleLLM   │
│+ base_url   │   │+ base_url            │
│统一↔Anthropic│   │统一↔OpenAI           │
│  格式转换    │   │  格式转换             │
└─────────────┘   └──────────────────────┘
```

## 文件改动清单

### 1. `agent/llm.py` — 核心改动（最大）

#### 1.1 定义统一消息格式

在文件开头新增统一数据结构，`core.py` 构建和消费的都是这些结构：

```python
@dataclass
class ToolCall:
    """统一工具调用结构"""
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class LLMResponse:
    """统一响应结构"""
    text: str                    # 文本回复（可为空）
    tool_calls: List[ToolCall]   # 工具调用列表（可为空）
    stop_reason: str             # "end_turn" / "tool_use"

@dataclass
class ToolResult:
    """统一工具结果结构"""
    tool_call_id: str
    content: str
    is_error: bool
```

#### 1.2 更新 `BaseLLMClient` 接口

```python
class BaseLLMClient:
    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],  # 统一格式的消息列表
        tools: List[Dict[str, Any]],     # 统一的 tool schema
    ) -> LLMResponse:
        raise NotImplementedError
```

messages 格式统一为：
```python
# 用户消息
{"role": "user", "content": "用户输入文本"}

# 助手消息（从 LLMResponse 构建）
{"role": "assistant", "text": "...", "tool_calls": [...]}

# 工具结果
{"role": "tool_result", "results": [ToolResult(...)]}
```

#### 1.3 `AnthropicLLM` 改造

- 构造函数新增 `base_url: str = ""` 参数
- 在 `generate()` 内部：
  - **入方向**：统一格式 → Anthropic 格式（content blocks, tool_use/tool_result）
  - **出方向**：Anthropic 响应 → `LLMResponse`（统一格式）

```python
class AnthropicLLM(BaseLLMClient):
    def __init__(self, *, api_key: str, model: str, max_tokens: int = 1024, base_url: str = ""):
        if anthropic is None:
            raise RuntimeError("The 'anthropic' package is not installed.")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, *, system_prompt, messages, tools) -> LLMResponse:
        # 1. 将统一消息格式转换为 Anthropic 格式
        anthropic_messages = self._to_anthropic_messages(messages)
        anthropic_tools = self._to_anthropic_tools(tools)

        # 2. 调用 API
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=anthropic_tools,
            messages=anthropic_messages,
        )

        # 3. 将 Anthropic 响应转换为统一格式
        return self._parse_response(response)

    def _to_anthropic_messages(self, messages):
        """统一格式 -> Anthropic content blocks 格式"""
        result = []
        for msg in messages:
            role = msg["role"]
            if role == "user":
                result.append({"role": "user", "content": msg["content"]})
            elif role == "assistant":
                # 重建 Anthropic content blocks
                content = []
                if msg.get("text"):
                    content.append({"type": "text", "text": msg["text"]})
                for tc in msg.get("tool_calls", []):
                    content.append({
                        "type": "tool_use",
                        "id": tc.id if isinstance(tc, ToolCall) else tc["id"],
                        "name": tc.name if isinstance(tc, ToolCall) else tc["name"],
                        "input": tc.arguments if isinstance(tc, ToolCall) else tc["arguments"],
                    })
                result.append({"role": "assistant", "content": content})
            elif role == "tool_result":
                # Anthropic 要求 tool_result 在 user role 下
                content = []
                for tr in msg["results"]:
                    content.append({
                        "type": "tool_result",
                        "tool_use_id": tr.tool_call_id if isinstance(tr, ToolResult) else tr["tool_call_id"],
                        "content": tr.content if isinstance(tr, ToolResult) else tr["content"],
                        "is_error": tr.is_error if isinstance(tr, ToolResult) else tr["is_error"],
                    })
                result.append({"role": "user", "content": content})
        return result

    def _to_anthropic_tools(self, tools):
        """统一 tool schema 直接兼容 Anthropic 格式（name, description, input_schema）"""
        return tools  # 当前 tools.py 的 definition() 输出已经是 Anthropic 格式

    def _parse_response(self, response) -> LLMResponse:
        """Anthropic 响应 -> 统一格式"""
        text_parts = []
        tool_calls = []
        for block in response.content:
            b = _block_to_dict(block)
            if b.get("type") == "text":
                text_parts.append(b.get("text", ""))
            elif b.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=b["id"],
                    name=b["name"],
                    arguments=b.get("input", {}),
                ))
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
        )
```

#### 1.4 新增 `OpenAICompatibleLLM`

```python
try:
    import openai
except ImportError:
    openai = None

class OpenAICompatibleLLM(BaseLLMClient):
    def __init__(self, *, api_key: str, model: str, max_tokens: int = 1024, base_url: str = ""):
        if openai is None:
            raise RuntimeError("The 'openai' package is not installed. Run 'pip install openai'.")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**client_kwargs)
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, *, system_prompt, messages, tools) -> LLMResponse:
        # 1. 统一格式 -> OpenAI 格式
        openai_messages = self._to_openai_messages(system_prompt, messages)
        openai_tools = self._to_openai_tools(tools)

        # 2. 调用 API
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": openai_messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
        response = self.client.chat.completions.create(**kwargs)

        # 3. OpenAI 响应 -> 统一格式
        return self._parse_response(response)

    def _to_openai_messages(self, system_prompt, messages):
        result = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg["role"]
            if role == "user":
                result.append({"role": "user", "content": msg["content"]})
            elif role == "assistant":
                oai_msg = {"role": "assistant"}
                if msg.get("text"):
                    oai_msg["content"] = msg["text"]
                if msg.get("tool_calls"):
                    oai_msg["tool_calls"] = [
                        {
                            "id": tc.id if isinstance(tc, ToolCall) else tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc.name if isinstance(tc, ToolCall) else tc["name"],
                                "arguments": json.dumps(
                                    tc.arguments if isinstance(tc, ToolCall) else tc["arguments"]
                                ),
                            },
                        }
                        for tc in msg["tool_calls"]
                    ]
                result.append(oai_msg)
            elif role == "tool_result":
                for tr in msg["results"]:
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id if isinstance(tr, ToolResult) else tr["tool_call_id"],
                        "content": tr.content if isinstance(tr, ToolResult) else tr["content"],
                    })
        return result

    def _to_openai_tools(self, tools):
        """统一 tool schema -> OpenAI function calling 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in tools
        ]

    def _parse_response(self, response) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))
        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )
```

#### 1.5 新增工厂函数

```python
def create_llm(
    *,
    provider: str,
    api_key: str,
    model: str,
    max_tokens: int = 1024,
    base_url: str = "",
) -> BaseLLMClient:
    provider = provider.lower()
    if provider == "anthropic":
        return AnthropicLLM(api_key=api_key, model=model, max_tokens=max_tokens, base_url=base_url)
    elif provider in ("openai", "deepseek", "openai-compatible"):
        return OpenAICompatibleLLM(api_key=api_key, model=model, max_tokens=max_tokens, base_url=base_url)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
```

#### 1.6 保留 `extract_text()` 辅助函数

改为从统一格式提取：

```python
def extract_text(response: LLMResponse) -> str:
    return response.text
```

### 2. `agent/config.py` — 通用化配置

```python
@dataclass
class AgentConfig:
    # 通用 LLM 配置
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic")
    )
    llm_api_key: str = field(
        default_factory=lambda: os.getenv(
            "LLM_API_KEY", os.getenv("ANTHROPIC_API_KEY", "")
        )
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv(
            "LLM_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        )
    )
    llm_base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "")
    )
    llm_max_tokens: int = 1024
    enabled_tools: Tuple[str, ...] = ("read_file", "write_file", "git_run")

    # 向后兼容属性
    @property
    def anthropic_api_key(self) -> str:
        return self.llm_api_key

    @property
    def anthropic_model(self) -> str:
        return self.llm_model

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)
```

环境变量优先级：`LLM_*` > `ANTHROPIC_*` > 默认值

### 3. `agent/core.py` — 适配统一消息格式

#### 3.1 修改 imports

```python
from agent.llm import BaseLLMClient, LLMResponse, ToolCall, ToolResult, create_llm
```

#### 3.2 修改 `_build_default_llm`

```python
def _build_default_llm(self) -> Optional[BaseLLMClient]:
    if not self.config.llm_enabled:
        return None
    return create_llm(
        provider=self.config.llm_provider,
        api_key=self.config.llm_api_key,
        model=self.config.llm_model,
        max_tokens=self.config.llm_max_tokens,
        base_url=self.config.llm_base_url,
    )
```

#### 3.3 修改 `_run_llm_loop` — 使用统一格式

当前 `core.py` 直接操作 Anthropic 格式的 content blocks（`tool_use`、`tool_result`），需要改为操作统一格式。

**核心变化**：

```python
def _run_llm_loop(self, messages, original_command):
    working_messages = list(messages)
    for _ in range(8):
        response = self.llm.generate(
            system_prompt=self._system_prompt(),
            messages=working_messages,
            tools=[tool.definition() for tool in self.tools.values()],
        )

        # 构建统一格式的 assistant 消息
        assistant_message = {
            "role": "assistant",
            "text": response.text,
            "tool_calls": response.tool_calls,
        }

        if response.tool_calls:
            tool_results = []
            for tc in response.tool_calls:
                tool = self.tools[tc.name]
                tool_input = dict(tc.arguments)
                if tool.requires_approval:
                    self.pending_approval = PendingApproval(
                        base_messages=working_messages,
                        assistant_message=assistant_message,
                        tool_name=tc.name,
                        tool_use_id=tc.id,
                        tool_input=tool_input,
                    )
                    return AgentResponse(
                        ok=True,
                        command=original_command,
                        message=tool.approval_prompt(tool_input) + " [yes/no]",
                        awaiting_confirmation=True,
                    )

                result = tool.execute(tool_input)
                tool_results.append(ToolResult(
                    tool_call_id=tc.id,
                    content=result.content,
                    is_error=not result.ok,
                ))

            working_messages = working_messages + [
                assistant_message,
                {"role": "tool_result", "results": tool_results},
            ]
            continue

        self.history = working_messages + [assistant_message]
        return AgentResponse(
            ok=True,
            command=original_command,
            message=response.text or "No text response returned.",
        )

    return AgentResponse(
        ok=False,
        command=original_command,
        stderr="LLM tool loop exceeded the maximum number of steps.",
        returncode=1,
    )
```

#### 3.4 修改 `_handle_approval` — 统一 tool_result 格式

```python
def _handle_approval(self, user_input):
    pending = self.pending_approval
    self.pending_approval = None

    approved = user_input.lower() in {"y", "yes"}
    tool = self.tools[pending.tool_name]

    if approved:
        result = tool.execute(pending.tool_input)
    else:
        result = ToolExecutionResult(ok=False, content="User denied tool execution.")

    tool_result_message = {
        "role": "tool_result",
        "results": [ToolResult(
            tool_call_id=pending.tool_use_id,
            content=result.content,
            is_error=not result.ok,
        )],
    }
    messages = pending.base_messages + [pending.assistant_message, tool_result_message]
    return self._run_llm_loop(messages, user_input)
```

### 4. `agent/cli.py` — 更新提示信息

```python
if agent.llm is None:
    print("LLM_API_KEY not found. Falling back to direct shell execution.")
else:
    print(f"LLM enabled (provider={agent.config.llm_provider}, model={agent.config.llm_model}) with tools.")
```

### 5. `requirements.txt` — 新增依赖

```
anthropic>=0.39.0
openai>=1.0.0
```

### 6. `tests/test_agent.py` — 更新测试

#### 6.1 更新 `FakeLLM`

已经继承 `BaseLLMClient`，接口不变，但需要返回新的 `LLMResponse` 格式：

```python
# 旧格式
LLMResponse(
    stop_reason="tool_use",
    content=[{"type": "tool_use", "id": "toolu_write_1", "name": "write_file", "input": {...}}],
)

# 新格式
LLMResponse(
    text="",
    tool_calls=[ToolCall(id="toolu_write_1", name="write_file", arguments={...})],
    stop_reason="tool_use",
)
```

#### 6.2 更新断言

`_handle_approval` 中 `tool_result` 格式变了，相关断言需更新。

#### 6.3 新增测试

- 测试 `create_llm()` 工厂函数对不同 provider 的分发
- 测试 config 环境变量优先级（`LLM_*` > `ANTHROPIC_*`）
- 测试 `AnthropicLLM` 和 `OpenAICompatibleLLM` 的消息格式转换

## 使用方式

### Anthropic（默认，行为不变）

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python main.py
```

### Anthropic + 自定义 base_url

```bash
export LLM_API_KEY="sk-ant-..."
export LLM_BASE_URL="https://my-proxy.com/v1"
python main.py
```

### OpenAI

```bash
export LLM_PROVIDER="openai"
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4o"
python main.py
```

### DeepSeek

```bash
export LLM_PROVIDER="deepseek"
export LLM_API_KEY="sk-..."
export LLM_MODEL="deepseek-chat"
export LLM_BASE_URL="https://api.deepseek.com"
python main.py
```

### 任意 OpenAI 兼容 API

```bash
export LLM_PROVIDER="openai-compatible"
export LLM_API_KEY="..."
export LLM_MODEL="my-model"
export LLM_BASE_URL="https://my-llm-api.com/v1"
python main.py
```

## 不变的部分

- `agent/policy.py` — 不涉及 LLM，无需改动
- `agent/shell.py` — 不涉及 LLM，无需改动
- `agent/tools.py` — tool schema 格式（`name`, `description`, `input_schema`）保持不变，Anthropic 和 OpenAI 的转换在各自 LLM 类内部处理

## TODO

- [ ] 1. 更新 `agent/config.py` — 通用化配置
- [ ] 2. 更新 `agent/llm.py` — 统一消息格式 + AnthropicLLM 改造 + 新增 OpenAICompatibleLLM + 工厂函数
- [ ] 3. 更新 `agent/core.py` — 适配统一消息格式
- [ ] 4. 更新 `agent/cli.py` — 更新提示信息
- [ ] 5. 更新 `requirements.txt` — 新增 openai 依赖
- [ ] 6. 更新 `tests/test_agent.py` — 适配新格式 + 新增测试
- [ ] 7. 运行测试确保全部通过
