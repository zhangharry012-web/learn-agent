# Research: LLM Tool Loop 超限错误分析

## 1. 问题描述

当 coding agent 被要求执行复杂任务（如"分析一个项目然后修改代码"）时，报错：

```
LLM exceeded the maximum tool interaction limit.
```

## 2. 错误根因定位

### 2.1 硬编码的步数上限

**文件**: `agent/runtime/agent.py:35`

```python
MAX_LLM_TOOL_STEPS = 8
```

这是一个模块级常量，**硬编码为 8**，没有任何配置化手段可以修改。

### 2.2 错误触发逻辑

**文件**: `agent/runtime/agent.py:260-392` — `_run_llm_loop` 方法

核心循环结构：

```python
def _run_llm_loop(self, messages, original_command):
    working_messages = list(messages)
    format_retry_used = False
    for step in range(MAX_LLM_TOOL_STEPS):   # 最多 8 次迭代
        response = self.llm.generate(...)
        # ... 处理 tool calls ...
        if response.tool_calls:
            # 执行工具，将结果追加到 working_messages
            working_messages = working_messages + [assistant_message, tool_result_message]
            continue   # 继续下一轮迭代
        # 无 tool call → 返回最终文本
        return AgentResponse(ok=True, ...)

    # for 循环耗尽 → 报错
    self.observability.log_event(LLM_LOOP_LIMIT_EXCEEDED, ...)
    return AgentResponse(
        ok=False,
        stderr='LLM exceeded the maximum tool interaction limit.',
        returncode=1,
    )
```

关键点：
- 每次 LLM 调用（无论返回多少个 tool call）消耗 **1 个 step**
- 但如果遇到 `requires_approval` 的工具（exec、git_run），循环会**中断并返回**，等用户确认后再重新进入循环——此时 step 计数**从 0 重新开始**
- 只有不需要审批的工具（read_file、write_file、edit_file、inspect_path、git_inspect、read_only_command、verify_command）才会在循环内消耗 step

### 2.3 为什么"分析项目+修改代码"会超限

一个典型的"分析项目并修改代码"任务所需步骤：

| Step | 操作 | 工具 | 需审批? |
|------|------|------|---------|
| 1 | 查看项目结构 | `inspect_path` | 否 |
| 2 | 读取主文件 | `read_file` | 否 |
| 3 | 读取配置文件 | `read_file` | 否 |
| 4 | 读取依赖文件 | `read_file` | 否 |
| 5 | 读取测试文件 | `read_file` | 否 |
| 6 | 分析后决定修改 | `write_file`/`edit_file` | 否 |
| 7 | 再次修改 | `edit_file` | 否 |
| 8 | 验证修改 | `verify_command` | 否 |
| 9+ | 还需要继续... | | |

8 步上限在项目分析场景下极其容易被耗尽。每次 LLM 调用只能包含一批 tool calls，但 LLM 通常倾向于逐步执行（每次只调一个工具），这意味着 8 步最多只能执行 8 个工具操作。

### 2.4 对比其他框架

| 框架 | 默认步数限制 |
|------|-------------|
| LangChain | 10（`max_iterations`） |
| AutoGen | 10（`max_consecutive_auto_reply`） |
| CrewAI | 可配置，默认较高 |
| Claude Code | 无硬性上限 |
| **本项目** | **8（硬编码）** |

本项目的 8 步限制是最低的，且无法配置。

## 3. 配置体系分析

**文件**: `agent/config.py`

当前 `AgentConfig` dataclass 支持通过 `.env` 文件配置以下参数：
- `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL`
- `LLM_MAX_TOKENS` / `LLM_FALLBACK_MAX_TOKENS`
- `OBSERVABILITY_*` 系列
- `VERIFY_*` 系列

**但没有** `LLM_MAX_TOOL_STEPS` 或类似的配置项。

配置读取机制使用 `_get_env_int()` 辅助函数从 `.env` 文件读取，已有现成的基础设施可以复用。

## 4. System Prompt 分析

**文件**: `agent/runtime/messages.py:23-32`

当前 system prompt 没有引导 LLM 高效使用工具的策略，例如：
- 没有提示 LLM 在单次响应中合并多个工具调用
- 没有提示 LLM 优先进行规划再执行
- 没有提示 LLM 注意步数限制

## 5. 测试覆盖

**文件**: `tests/test_agent_runtime.py`

现有测试使用 `FakeLLM` mock，每个测试最多测 2-4 轮 LLM 调用。没有针对 loop limit 超限场景的专门测试。需要补充相关测试。

## 6. 文件修改影响范围

需要修改的文件：
1. `agent/config.py` — 新增 `llm_max_tool_steps` 配置字段
2. `agent/runtime/agent.py` — 将硬编码常量改为使用配置值
3. `.env.example` — 文档化新环境变量
4. `agent/runtime/messages.py` — 优化 system prompt 引导高效工具使用
5. `tests/test_agent_runtime.py` — 新增 loop limit 相关测试

不需要修改的文件：
- `agent/llm/` — LLM 客户端无需变更
- `agent/tools/` — 工具定义无需变更
- `agent/policy.py` — 安全策略无需变更
- `agent/shell.py` — Shell 执行器无需变更
