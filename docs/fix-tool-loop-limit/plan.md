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

---

## 后续优化：日志 Payload 精简

### 背景

基于一次实际 agent 会话日志（9 次 LLM 调用、8 次工具调用、41,487 tokens）的分析，发现以下日志冗余问题：

### 问题分析

| 优先级 | 问题 | 说明 |
|--------|------|------|
| P0 | `tool.execution.completed` 中 `tool_input` 记录完整文件内容 | write_file/edit_file 的 `content` 字段可达数百行，导致日志体积膨胀 |
| P1 | LLM 误用 `read_only_command` 执行 build 命令 | 日志中 step 6 用 `read_only_command` 执行 `npm run build` 被拒，step 7 改用 `exec` 重试，浪费 2 步 |
| P2 | `command.completed` 重复记录完整 LLM 响应文本 | `message`/`stdout`/`stderr` 字段内容已在 `llm.response.completed` 和 `shell.execution.completed` 中记录 |
| P2 | `tool.approval.requested` 与 `tool.execution.completed` 中 `tool_input` 重复 | 同一次工具调用的输入被记录两次 |

### 修改方案

#### 1. `agent/runtime/observability.py` — 新增 `preview_tool_input()` 方法

```python
TOOL_INPUT_CONTENT_PREVIEW_CHARS = 200
TOOL_INPUT_LARGE_KEYS = frozenset({'content'})

def preview_tool_input(self, tool_input: Any) -> Any:
    """对 tool_input 中的已知大值字段使用更短的截断阈值（200 字符）"""
    if not isinstance(tool_input, dict):
        return self.preview(tool_input)
    result = {}
    for key, val in tool_input.items():
        if key in TOOL_INPUT_LARGE_KEYS and isinstance(val, str) and len(val) > TOOL_INPUT_CONTENT_PREVIEW_CHARS:
            result[key] = val[:TOOL_INPUT_CONTENT_PREVIEW_CHARS] + f'... [truncated ...]'
        else:
            result[key] = self.preview(val)
    return result
```

#### 2. `agent/runtime/agent.py` — 新增 `_log_tool_execution()` 辅助方法

```python
def _log_tool_execution(
    self, tool_name, approved, ok, tool_input, result_content,
    duration_ms, *, after_approval=False,
) -> None:
    payload = {
        'tool_name': tool_name, 'approved': approved,
        'ok': ok, 'duration_ms': duration_ms,
    }
    if after_approval:
        payload['tool_input'] = '[see tool.approval.requested]'
    else:
        payload['tool_input'] = self.observability.preview_tool_input(tool_input)
    payload['result'] = result_content
    self._log(TOOL_EXECUTION_COMPLETED, payload)
```

同时移除 `command.completed` 中的 `message`/`stdout`/`stderr` 字段。

#### 3. `agent/runtime/messages.py` — 补充工具选择指引

**设计决策：为什么放在 system prompt 而非 tool description**

将 `read_only_command` 与 `exec` 的选择指引放在 system prompt 而非 tool description 中，理由如下：

1. **这是跨工具的路由决策，不是单工具的用法说明**。问题本质是 LLM 在两个工具之间做错了选择，这是一个工具选择（tool routing）问题。system prompt 是 LLM 做决策前最先读到的全局上下文，适合放置跨工具的路由规则。

2. **tool description 的影响范围有限**。LLM 只有在"已经倾向于选择某个工具"时才会重点关注该工具的 description。如果 LLM 一开始就错误地倾向于 `read_only_command`，它读到的是 `read_only_command` 的 description——纠正效果不如在 system prompt 中提前拦截。

3. **实际日志验证了单靠 tool description 不够**。`read_only_command` 的工具定义中已经限制了只允许只读命令，但 LLM 仍尝试用它执行 `npm run build`，说明需要在更上游的 system prompt 层面强化。

新增的 prompt 内容：
```
IMPORTANT: read_only_command is restricted to pure read-only inspection commands
(ls, cat, head, tail, wc, find, file, stat, du, etc.). Any command that builds,
compiles, runs, installs, or has side effects (npm run build, node, python,
pip install, make, etc.) MUST use exec instead.
```

**补充说明**：最佳实践是两处同时做——system prompt 做全局路由指引，tool description 做单工具约束。当前优先在 system prompt 层面解决，后续如仍有误用可在 tool description 中也加上排除列表形成双重保障。

### TODO

- [x] 1. `agent/runtime/observability.py`: 新增 `TOOL_INPUT_CONTENT_PREVIEW_CHARS` 常量和 `preview_tool_input()` 方法
- [x] 2. `agent/runtime/agent.py`: 新增 `_log_tool_execution()` 辅助方法，替换两处内联日志
- [x] 3. `agent/runtime/agent.py`: `command.completed` 事件移除 `message`/`stdout`/`stderr`
- [x] 4. `agent/runtime/messages.py`: system prompt 补充 `read_only_command` vs `exec` 选择指引
- [x] 5. 运行测试确保所有测试通过（71/71 passed）
- [x] 6. 推送到远端分支
