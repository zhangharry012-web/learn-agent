# Plan: 修复 LLM Tool Loop 超限错误

## Overview

将硬编码的 `MAX_LLM_TOOL_STEPS = 8` 改为可配置参数，提高默认值至 25，并优化 system prompt 引导 LLM 更高效地使用工具，同时补充相关测试。

## 架构设计

```
当前: agent.py 硬编码 MAX_LLM_TOOL_STEPS = 8
          ↓
目标: config.py 新增 llm_max_tool_steps 字段
       → .env 文件可配置 LLM_MAX_TOOL_STEPS
       → agent.py 从 self.config 读取上限值
       → messages.py 优化 prompt 引导高效工具使用
```

## 修改方案

### 1. `agent/config.py` — 新增配置字段

在 `AgentConfig` dataclass 中新增：

```python
DEFAULT_MAX_TOOL_STEPS = 25

@dataclass
class AgentConfig:
    # ... 已有字段 ...
    llm_max_tool_steps: int = field(
        default_factory=lambda: _get_env_int('LLM_MAX_TOOL_STEPS', DEFAULT_MAX_TOOL_STEPS)
    )
```

**设计决策**：
- 默认值从 8 提升到 25，覆盖"分析项目+修改代码"这类场景（通常需要 10-20 步）
- 通过 `.env` 文件可自定义（`LLM_MAX_TOOL_STEPS=30`）
- 复用已有的 `_get_env_int()` 读取机制，保持一致性

### 2. `agent/runtime/agent.py` — 使用配置值替代硬编码

```python
# 删除: MAX_LLM_TOOL_STEPS = 8
# 修改 _run_llm_loop 方法:

def _run_llm_loop(self, messages, original_command):
    max_steps = self.config.llm_max_tool_steps   # 从配置读取
    ...
    for step in range(max_steps):
        ...
    # 超限报错时也使用配置值
    self.observability.log_event(
        LLM_LOOP_LIMIT_EXCEEDED,
        self.session_id,
        {'command': original_command, 'max_steps': max_steps},
    )
```

**不改变的部分**：
- 循环内部的工具执行逻辑不变
- approval 机制不变
- observability 日志格式不变（只是 max_steps 值变了）

### 3. `agent/runtime/messages.py` — 优化 System Prompt

在 system prompt 中追加工具使用效率指引：

```python
def build_system_prompt() -> str:
    return (
        'You are a shell-oriented local coding agent. ...'
        # 新增以下指引:
        'When analyzing a project, batch related inspections efficiently — '
        'for example, combine multiple file reads or inspections in a single '
        'turn when possible. Plan your approach before executing to minimize '
        'the number of tool interactions needed.'
    )
```

### 4. `.env.example` — 文档化新配置

```ini
# Maximum LLM tool interaction steps per command (default: 25)
LLM_MAX_TOOL_STEPS=25
```

### 5. `tests/test_agent_runtime.py` — 补充测试

新增测试用例：
- 验证可通过 `AgentConfig(llm_max_tool_steps=N)` 自定义上限
- 验证循环在自定义上限后正确终止并返回错误

## 不修改的文件

- `agent/llm/` — LLM 客户端层无需变更
- `agent/tools/` — 工具定义无需变更
- `agent/policy.py` — 安全策略无需变更
- `agent/shell.py` — Shell 执行器无需变更
- `main.py` — 入口文件无需变更

## TODO

- [x] 1. `agent/config.py`: 新增 `DEFAULT_MAX_TOOL_STEPS` 常量和 `llm_max_tool_steps` 字段
- [x] 2. `agent/runtime/agent.py`: 删除硬编码常量，从 `self.config.llm_max_tool_steps` 读取
- [x] 3. `agent/runtime/messages.py`: 优化 system prompt 添加效率指引
- [x] 4. `.env.example`: 文档化 `LLM_MAX_TOOL_STEPS` 环境变量
- [x] 5. `tests/test_agent_runtime.py`: 补充 loop limit 可配置的测试
- [x] 6. 运行测试确保所有测试通过（19/19 passed）
- [x] 7. 推送到远端分支
