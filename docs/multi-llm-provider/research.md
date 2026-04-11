# Research: learn-agent LLM 多 Provider 支持

## 当前项目结构

```
learn-agent/
├── main.py              # 入口，委托给 cli 模块
├── requirements.txt     # 唯一依赖: anthropic>=0.39.0
├── agent/
│   ├── __init__.py
│   ├── cli.py           # 交互式 CLI，会话管理
│   ├── config.py        # 配置管理（API key、model）
│   ├── core.py          # Agent 主类，编排所有操作
│   ├── llm.py           # LLM 客户端封装（当前仅 Anthropic）
│   ├── policy.py        # 安全策略（命令拒绝列表）
│   ├── shell.py         # 子进程执行封装
│   └── tools.py         # 工具实现（read_file, write_file, git_run）
├── tests/
│   └── test_agent.py    # 单元测试
└── docs/
    └── architecture.md
```

## 当前 LLM 实现分析

### 1. 抽象层 (`agent/llm.py`)

已有 `BaseLLMClient` 抽象基类，定义了 `generate()` 接口：

```python
class BaseLLMClient:
    def generate(self, *, system_prompt, messages, tools) -> LLMResponse:
        raise NotImplementedError
```

唯一实现 `AnthropicLLM`：
- 构造函数接受 `api_key`、`model`、`max_tokens`
- **不支持 `base_url`**
- 使用 `anthropic.Anthropic(api_key=api_key)` 创建客户端
- `generate()` 调用 `client.messages.create()` 并将响应转为 `LLMResponse`

辅助函数：
- `_block_to_dict()`: 将 Anthropic API 的 content block 转为字典
- `extract_text()`: 从 LLM 响应中提取文本

### 2. 配置管理 (`agent/config.py`)

```python
@dataclass
class AgentConfig:
    anthropic_api_key: str   # 从 ANTHROPIC_API_KEY 环境变量
    anthropic_model: str     # 从 ANTHROPIC_MODEL，默认 claude-sonnet-4-20250514
    llm_max_tokens: int = 1024
    enabled_tools: Tuple[str, ...] = (...)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)
```

**问题**：字段名和环境变量名都是 Anthropic 专用的，没有通用配置。

### 3. Agent 初始化 (`agent/core.py`)

```python
def _build_default_llm(self) -> Optional[BaseLLMClient]:
    if not self.config.llm_enabled:
        return None
    return AnthropicLLM(
        api_key=self.config.anthropic_api_key,
        model=self.config.anthropic_model,
        max_tokens=self.config.llm_max_tokens,
    )
```

**硬编码了 AnthropicLLM**，无法切换 provider。

### 4. LLM 调用方式 (`agent/core.py`)

```python
response = self.llm.generate(
    system_prompt=self._system_prompt(),
    messages=working_messages,
    tools=[tool.definition() for tool in self.tools.values()],
)
```

使用的 messages 格式和 tools 格式遵循 Anthropic 的 API 规范（content blocks 数组，tool_use/tool_result 类型）。

### 5. 依赖

`requirements.txt` 仅有 `anthropic>=0.39.0`，无其他依赖。

## 关键发现

1. **已有抽象层**：`BaseLLMClient` 接口设计合理，新增 provider 只需新增实现类
2. **消息格式耦合**：当前 messages 和 tools 格式是 Anthropic 风格的，其他 provider（OpenAI 等）格式不同
3. **响应格式耦合**：`_block_to_dict()` 专门处理 Anthropic 的 content block 格式
4. **配置无扩展性**：config 字段名绑定了 Anthropic
5. **无 base_url 支持**：Anthropic SDK 本身支持 `base_url` 参数，但项目未暴露

## 技术方案对比

### 方案 A: 使用 LiteLLM（统一 LLM 库）
- **优点**：一个库支持 100+ provider，统一 OpenAI 格式，社区活跃
- **缺点**：引入较大依赖，需要适配消息格式（当前是 Anthropic 格式）
- **适合**：快速支持多 provider，减少维护成本

### 方案 B: 使用 OpenAI SDK + base_url
- **优点**：OpenAI SDK 是事实标准，大多数 provider 兼容其 API 格式；轻量
- **缺点**：需要将消息格式从 Anthropic 转换为 OpenAI 格式；部分 Anthropic 专有功能可能丢失
- **适合**：需要兼容 deepseek/自定义 endpoint 等 OpenAI 兼容 API

### 方案 C: 保留 Anthropic + 新增 OpenAI 兼容客户端
- **优点**：保留现有 Anthropic 功能不受影响，新增 OpenAI 兼容客户端支持 base_url
- **缺点**：需要维护两套消息格式转换逻辑
- **适合**：渐进式迁移，不破坏现有功能
