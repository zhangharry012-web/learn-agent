# 自动验证执行方案设计

## 概述

目标是在 coding agent 修改代码后，尽量自动执行验证/测试/构建命令，减少用户频繁确认，同时继续保持当前项目已经建立的安全边界：窄工具优先、任意 shell 严格审批、执行前强校验、所有行为可审计。

结论先行：**推荐新增 `verify_command` 专用工具，并采用“平台内置安全规则 + 项目级策略文件”双重判定**。短期可以先上通用 allowlist 版本，长期再引入仓库内策略文件。

---

## 设计目标

| 目标 | 含义 |
|---|---|
| 减少打断 | 改完代码后的常见验证尽量免人工确认 |
| 明确边界 | 自动验证与任意 shell 必须明确分离 |
| 可校验 | 执行前必须能做强约束，而不是仅靠模型理解 |
| 可演进 | 能覆盖 Python / Go / Node 等常见生态 |
| 可审计 | 每次自动执行都能记录原因、规则命中、结果 |

---

## 非目标

以下能力不属于“自动验证执行”范围：

- 任意 shell 自动执行
- 安装依赖、升级依赖、发布、部署
- 联网下载与拉取外部资源
- 执行项目内任意脚本
- 修改 workspace 外文件
- 无约束地运行 package script / make target / shell script

---

## 方案总览

### 方案 A：保留 `exec`，仅通过审批策略放行部分验证命令

#### 核心思路
不新增工具，仍然让模型调用 `exec`。但在审批环节增加规则：如果命令被识别为低风险验证命令，则无需确认；否则继续审批。

#### 目标流程

```text
LLM -> exec(command)
      -> policy.evaluate_auto_approval(command)
         -> allowed verify command -> 直接执行
         -> other command -> 等待人工审批
```

#### 设计细节

1. `ExecTool` 保持现有输入：

```json
{
  "command": "python -m unittest tests.test_agent_runtime"
}
```

2. 在运行时新增一层自动审批判断，例如：
   - `python -m unittest ...`
   - `go test ./...`
   - `npm run test`

3. 若命中自动审批规则，则不进入 `PendingApproval`，直接执行。

#### 需要修改的代码点

- `agent/runtime/agent.py`
  - 在 tool approval 分支增加自动放行判断。
- `agent/policy.py`
  - 新增针对 exec 的子类命令分类逻辑。
- `tests/test_agent_runtime.py`
  - 新增 exec 工具在不同命令下自动审批 / 人工审批分支测试。

#### 优点

- 代码改动表面最少；
- 不增加新工具；
- 快速可用。

#### 缺点

- `exec` 语义被污染：同一个工具有时自动、有时审批；
- 模型更难稳定理解边界；
- 文档描述会变复杂；
- 审计难区分“安全验证执行”和“任意 shell”；
- 长期维护最差。

#### 适用场景

- 只追求极短期落地；
- 可以接受后续再推翻重做。

#### 风险结论

**不推荐作为正式方案。**

---

### 方案 B：新增 `verify_command`，使用平台内置通用 allowlist

#### 核心思路
新增一个专门的验证执行工具。它默认免审批，但只允许受限的测试 / lint / build 命令，不允许任意 shell。

#### 工具边界

| 工具 | 责任 | 审批 |
|---|---|---|
| `verify_command` | 修改代码后的受控验证命令 | 默认免审批 |
| `exec` | 任意 shell 兜底 | 必须审批 |

#### 推荐接口

```json
{
  "argv": ["python", "-m", "unittest", "tests.test_agent_runtime"],
  "reason": "validate runtime changes",
  "cwd": "."
}
```

#### 为什么必须使用 `argv`

- 禁止 shell 拼接与解释；
- 方便精确匹配命令模式；
- 便于审计；
- 比原始 `command` 字符串更稳。

#### 允许的首批命令建议

##### Python
- `python -m unittest ...`
- `python3 -m unittest ...`
- `python -m pytest ...`
- `pytest ...`
- `ruff check ...`
- `mypy ...`

##### Go
- `go test ...`

##### Node
- `npm run test`
- `npm run lint`
- `npm run build`
- `pnpm test`
- `pnpm lint`
- `pnpm build`
- `yarn test`
- `yarn lint`
- `yarn build`

#### 默认拒绝的命令

- `python script.py`
- `python -m pip install ...`
- `go run ...`
- `go generate ...`
- `npm install`
- `npm publish`
- `npm exec`
- `npx ...`
- `bash xxx.sh`
- `sh xxx.sh`
- `make ...`（第一阶段建议全部不放开）

#### 通用校验规则

##### 1. shell token 拒绝
拒绝以下 token：
- `|`
- `&&`
- `;`
- `>`
- `>>`
- `<`
- `` ` ``
- `$()`

##### 2. 路径限制
- 所有路径参数必须在 workspace 内；
- 禁止 `..` 越界；
- 禁止绝对路径指向 workspace 外。

##### 3. cwd 限制
- `cwd` 必须为 repo root 或其子目录；
- 默认 `.`；
- 不允许用户传系统路径。

##### 4. 程序与子命令双重校验
例如：
- `go` 只允许 `test`
- `python` 只允许 `-m unittest` / `-m pytest`
- `npm run` 只允许 `test/lint/build`

##### 5. 资源限制
| 限制项 | 建议 |
|---|---|
| timeout | 默认 120s，按命令模板可覆盖 |
| 输出行数 | 截断到固定上限 |
| 并发数 | 每次只跑一个 verify tool |
| 返回内容 | 标准化 JSON，带 command/returncode/stdout/stderr |

#### 模块设计

```text
agent/tools/
├── verify_command_tool.py
├── registry.py
└── __init__.py
```

#### `verify_command_tool.py` 结构建议

```text
VerifyCommandTool
├── execute(payload)
├── _validate_payload(payload)
├── _validate_argv(argv)
├── _validate_python(argv)
├── _validate_go(argv)
├── _validate_node(argv)
├── _validate_paths(argv)
└── _build_run_options(payload)
```

#### 伪代码

```python
class VerifyCommandTool(BaseTool):
    name = 'verify_command'
    requires_approval = False

    def execute(self, payload):
        argv = self._parse_argv(payload)
        error = self._validate_argv(argv, payload)
        if error is not None:
            return ToolExecutionResult(ok=False, content=error)
        cwd = self._resolve_cwd(payload)
        result = self.shell_runner.run_argv(argv, cwd=cwd, timeout=self._timeout_for(argv))
        return self._json_result(result)
```

#### 需要修改的文件

```text
agent/tools/verify_command_tool.py        # 新增
agent/tools/registry.py                   # 注册工具
agent/tools/__init__.py                   # 导出工具
agent/config.py                           # enabled_tools 默认增加 verify_command；新增 verify 相关配置
README.md                                 # 新增工具边界说明
tests/test_tools.py                       # 工具级验证测试
tests/test_agent_runtime.py               # runtime 中 verify_command 免审批执行测试
```

#### 优点

- 和当前架构最一致；
- 语义清晰、可测试；
- 容易写出明确 description，引导模型正确选 tool；
- 易于扩展；
- 审计清晰。

#### 缺点

- 通用 allowlist 不够适配所有项目；
- 对 `npm run`、`make` 这类场景支持有限；
- 后续仍需要项目级自定义能力。

#### 风险结论

**推荐作为第一阶段落地方案。**

---

### 方案 C：新增 `verify_command`，并叠加项目级策略文件

#### 核心思路
在方案 B 基础上增加仓库内策略文件。自动执行必须同时满足：

1. 平台内置安全规则通过；
2. 仓库本地策略显式允许。

#### 策略文件建议

文件名候选：
- `.agent/verify-policy.json`
- `.agent/verify-policy.yaml`

推荐第一版用 JSON，解析简单、测试简单。

#### 建议 schema

```json
{
  "version": 1,
  "default_timeout_sec": 120,
  "allow": [
    {
      "id": "python-runtime-tests",
      "argv_prefix": ["python", "-m", "unittest"],
      "cwd": ".",
      "max_timeout_sec": 120,
      "allowed_path_patterns": ["^tests(?:/|\\.).*$", "^agent(?:/|\\.).*$"]
    },
    {
      "id": "go-unit-tests",
      "argv_prefix": ["go", "test"],
      "cwd": ".",
      "max_timeout_sec": 120,
      "allowed_arg_regex": ["^\./\.\.\.$", "^\./[a-zA-Z0-9_./-]+$"]
    },
    {
      "id": "npm-lint",
      "argv_exact": ["npm", "run", "lint"],
      "cwd": ".",
      "max_timeout_sec": 60
    }
  ],
  "deny_keywords": [
    "install",
    "publish",
    "deploy",
    "curl",
    "wget",
    "bash",
    "sh"
  ]
}
```

#### 判定流程

```text
verify_command(argv)
  -> 平台硬规则校验
     -> 不通过：拒绝
  -> 读取 .agent/verify-policy.json
     -> 文件不存在：走默认 allowlist 或保守拒绝
  -> 命中本地 allow rule
     -> 执行
  -> 未命中
     -> 拒绝并提示改用 exec 审批
```

#### 推荐行为模式

##### 模式 1：无策略文件时使用内置 allowlist
优点：开箱即用。
缺点：边界不如“必须显式声明”严格。

##### 模式 2：无策略文件时保守拒绝
优点：最安全。
缺点：体验较差。

##### 建议
第一阶段推荐“无策略文件时走内置 allowlist”；成熟后可支持配置成 strict mode。

#### 模块设计

```text
agent/
├── verify/
│   ├── __init__.py
│   ├── policy_loader.py
│   ├── rule_types.py
│   ├── matcher.py
│   └── defaults.py
└── tools/
    └── verify_command_tool.py
```

#### 组件职责

| 模块 | 职责 |
|---|---|
| `verify_command_tool.py` | 对外工具入口，做 payload 解析与执行 |
| `verify/defaults.py` | 平台内置 allowlist |
| `verify/policy_loader.py` | 读取 repo 策略文件 |
| `verify/matcher.py` | 规则匹配与判定 |
| `verify/rule_types.py` | 规则数据结构 |

#### 架构图

```text
LLM
  -> verify_command
       -> payload parsing
       -> hard security validation
       -> default allowlist matching
       -> repo policy matching
       -> timeout/output/cwd resolution
       -> shell_runner.run_argv(...)
       -> structured result
```

#### 需要新增的配置项

在 `agent/config.py` 中新增：

```python
verify_auto_approve_enabled: bool = True
verify_policy_file: str = '.agent/verify-policy.json'
verify_default_timeout_sec: int = 120
verify_require_repo_policy: bool = False
```

#### 需要新增的 observability 事件

- `verify.execution.requested`
- `verify.execution.completed`
- `verify.execution.rejected`

#### 需要新增的测试

##### `tests/test_tools.py`
- 允许 `python -m unittest`
- 拒绝 `python script.py`
- 拒绝 shell token
- 拒绝 workspace 外路径
- 命中 repo policy 的 `npm run lint`
- 未命中 repo policy 时拒绝

##### `tests/test_agent_runtime.py`
- verify_command 默认免审批
- verify_command 拒绝时返回错误结果但不崩溃
- verify 事件被记录

##### 新增 `tests/test_verify_policy.py`
- policy file 读取
- schema 校验
- argv_prefix / argv_exact 匹配
- deny keyword 生效

#### 优点

- 最符合多项目场景；
- 规则边界最清晰；
- 可解释性最强；
- 用户能自己调整仓库自动验证范围；
- 长期可维护性最好。

#### 缺点

- 实现成本最高；
- 需要设计与维护策略文件格式；
- 初期文档与测试工作更多。

#### 风险结论

**推荐作为长期正式方案。**

---

### 方案 D：命令风险评分系统

#### 核心思路
不采用简单 allowlist，而是将命令解析后打风险分：

- shell token +40
- 网络工具 +50
- install/publish +60
- package script +20
- workspace 外路径 +100
- 测试命令 -20

得分低于阈值自动执行，否则审批。

#### 优点
- 理论上灵活；
- 能减少显式规则数量。

#### 缺点
- 可解释性差；
- 边界不稳定；
- 容易产生误判；
- 不符合当前项目强调“窄工具强边界”的风格。

#### 风险结论

**不建议作为主方案，只适合未来辅助排序或推荐。**

---

## 推荐方案

### 推荐结论

采用分阶段路线：

1. **短期：方案 B**
   - 新增 `verify_command`
   - 使用结构化 `argv`
   - 实现平台内置 allowlist
   - 默认免审批

2. **中长期：演进到方案 C**
   - 引入 `.agent/verify-policy.json`
   - 用“平台硬规则 + 仓库策略”双重判定
   - 增加专门 observability 事件与策略测试

### 为什么不是方案 A
因为当前项目已经建立了非常清晰的工具边界。如果继续在 `exec` 里混自动审批，会直接破坏前面刚收敛好的结构。

### 为什么不是方案 D
因为当前项目更适合**规则清晰、测试稳定、可审计强**的方案，而不是统计式、评分式边界。

---

## 推荐方案的详细设计

## 一、工具接口

### 工具名

推荐：`verify_command`

### description 草案

> Execute a narrow set of verification, test, lint, and build commands inside the current workspace without human approval. Use this tool after modifying code when the goal is to validate the change safely. Do not use it for arbitrary shell commands, dependency installation, publishing, deployment, network access, or script execution outside the approved verification subset. If the command is outside this safe verification subset, use exec instead.

### input_schema 草案

```python
input_schema = {
    'type': 'object',
    'properties': {
        'argv': {
            'type': 'array',
            'items': {'type': 'string'},
            'description': 'Structured command argv for a safe verification command, for example ["python", "-m", "unittest", "tests.test_agent_runtime"].',
        },
        'cwd': {
            'type': 'string',
            'description': 'Optional relative working directory inside the workspace. Defaults to the workspace root.',
        },
        'reason': {
            'type': 'string',
            'description': 'Short reason for running the verification command.',
        },
    },
    'required': ['argv'],
}
```

---

## 二、校验规则

### 1. payload 校验
- `argv` 必须存在且非空；
- 每个元素必须是非空字符串；
- `cwd` 可选，但必须能解析到 workspace 内。

### 2. shell 逃逸拒绝
任何 `argv` 元素含以下模式直接拒绝：
- `|`
- `&&`
- `;`
- `>` / `>>`
- `<`
- `` ` ``
- `$(`

### 3. 语言生态校验
按首命令分支：

#### Python
允许：
- `python -m unittest ...`
- `python3 -m unittest ...`
- `python -m pytest ...`
- `pytest ...`
- `ruff check ...`
- `mypy ...`

拒绝：
- `python script.py`
- `python -m pip ...`
- `python -c ...`

#### Go
允许：
- `go test ...`

拒绝：
- `go run`
- `go install`
- `go generate`
- `go mod ...`

#### Node
允许：
- `npm run test`
- `npm run lint`
- `npm run build`
- `pnpm test`
- `pnpm lint`
- `pnpm build`
- `yarn test`
- `yarn lint`
- `yarn build`

拒绝：
- `npm install`
- `npm publish`
- `npm exec`
- `npx ...`
- 任意非 allowlist script 名

### 4. 路径参数校验
- 所有路径类参数都要尝试解析；
- 必须留在 workspace；
- 可以允许 `tests.test_xxx` 这类模块路径字符串，但不能把绝对路径放开。

### 5. 超时策略
| 命令类型 | 默认超时 |
|---|---|
| lint/check | 60s |
| unit tests | 120s |
| build | 180s |

### 6. 输出策略
统一返回 JSON：

```json
{
  "argv": ["python", "-m", "unittest", "tests.test_agent_runtime"],
  "cwd": ".",
  "returncode": 0,
  "stdout": "...",
  "stderr": "...",
  "rule_id": "python-unittest"
}
```

---

## 三、和现有工具的边界关系

| 用户意图 | 正确工具 | 说明 |
|---|---|---|
| 读文件内容 | `read_file` | 继续保持 |
| 看目录结构 | `inspect_path` | 继续保持 |
| 看文件摘要/元信息 | `read_only_command` | 继续保持 |
| 看 git 状态 | `git_inspect` | 继续保持 |
| 跑测试/lint/build 验证 | `verify_command` | 新增的免审批受限执行层 |
| 任意 shell | `exec` | 始终审批 |

`exec` 的 description 应进一步补一句：

> Do not use this tool for standard test, lint, or build verification commands when `verify_command` applies.

---

## 四、项目级策略文件扩展设计

### 目标
避免平台内置规则越来越重，同时让 repo 自己定义“本项目哪些验证命令是安全且值得自动执行的”。

### 策略文件位置
默认：`.agent/verify-policy.json`

### 解析顺序
```text
1. 读取平台默认规则
2. 若存在 repo policy，则加载 repo rule
3. 先跑硬拒绝规则
4. 再匹配 repo allow rule
5. 若未命中 repo allow，再回退默认 allow 或直接拒绝（可配置）
```

### 可扩展字段
- `argv_exact`
- `argv_prefix`
- `cwd`
- `max_timeout_sec`
- `allowed_arg_regex`
- `allowed_path_patterns`
- `allow_generated_artifacts`
- `description`

---

## 五、审计与可观测性设计

### 新增事件

```text
verify.execution.requested
verify.execution.completed
verify.execution.rejected
```

### 事件载荷建议

#### requested
```json
{
  "argv": ["go", "test", "./..."],
  "cwd": ".",
  "reason": "validate refactor"
}
```

#### completed
```json
{
  "argv": ["go", "test", "./..."],
  "cwd": ".",
  "rule_id": "go-test",
  "returncode": 0,
  "duration_ms": 3210
}
```

#### rejected
```json
{
  "argv": ["npm", "install"],
  "reason": "Dependency installation is outside the safe verification subset."
}
```

### 价值
- 可以分析最常用的自动验证命令；
- 可以收敛 allowlist；
- 可以定位误拒绝场景；
- 对安全审计有帮助。

---

## 六、落地实施顺序

### Phase 1：最小可用版

目标：先把 `verify_command` 跑通。

#### 改动文件结构

```text
agent/tools/
├── verify_command_tool.py   # 新增
├── registry.py              # 修改
└── __init__.py              # 修改

agent/config.py              # 修改
README.md                    # 修改
tests/test_tools.py          # 修改
tests/test_agent_runtime.py  # 修改
```

#### 实现范围
- 新增 `verify_command`
- 支持 python/go/node 的少量 allowlist
- 默认免审批
- 无 repo policy 文件
- 先不支持 make/cargo/自定义脚本

### Phase 2：项目策略文件

目标：让 repo 声明自己的自动验证边界。

#### 新增文件结构

```text
agent/verify/
├── __init__.py
├── defaults.py
├── matcher.py
├── policy_loader.py
└── rule_types.py

tests/test_verify_policy.py
```

### Phase 3：最小验证集推荐

目标：根据变更路径，自动优先选择更小的测试范围，而不是总跑全量测试。

例如：
- 改 `agent/runtime/*` -> 优先 `tests.test_agent_runtime`
- 改 `agent/llm/*` -> 优先 `tests.test_llm_openai`

这一步是体验增强，不影响核心安全边界。

---

## 优劣对比

| 方案 | 核心思路 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| A | 在 `exec` 内做自动审批 | 改动少，上线快 | 工具语义混乱，长期差 | 不推荐 |
| B | 新增 `verify_command` + 内置 allowlist | 清晰、稳、易测试 | 对多项目适配有限 | 推荐作为第一阶段 |
| C | `verify_command` + repo policy | 灵活、安全、可维护 | 实现成本更高 | 推荐作为长期正式方案 |
| D | 风险评分自动放行 | 理论灵活 | 边界模糊、难审计 | 不推荐作为主方案 |

---

## 最终建议

### 推荐路线

#### 建议 1
**不要修改 `exec` 的语义。**

`exec` 应继续保持：
- 任意 shell；
- 明确危险；
- 始终审批。

#### 建议 2
**新增 `verify_command` 作为“修改代码后自动验证”专用工具。**

它应该：
- 默认免审批；
- 输入使用结构化 `argv`；
- 执行前做强校验；
- 对 Python / Go / Node 提供有限支持。

#### 建议 3
**短期先做方案 B，长期演进到方案 C。**

也就是：
- 第一步先做内置 allowlist；
- 第二步引入 `.agent/verify-policy.json`；
- 第三步再做智能的最小验证集推荐。

### 原因总结

这个路线：
- 与当前项目现有工具架构最一致；
- 安全边界最清晰；
- 用户体验明显改善；
- 后续能持续收敛，而不是不断补 exec 特判。

---

## TODO

- [ ] 设计 `verify_command` 的最终 description、input_schema 与错误消息规范
- [ ] 新增 `agent/tools/verify_command_tool.py`
- [ ] 实现 `argv` 解析与通用拒绝规则
- [ ] 实现 Python allowlist 校验
- [ ] 实现 Go allowlist 校验
- [ ] 实现 Node allowlist 校验
- [ ] 将 `verify_command` 注册到 `agent/tools/registry.py`
- [ ] 在 `agent/tools/__init__.py` 中导出新工具
- [ ] 在 `agent/config.py` 中加入 verify 相关配置
- [ ] 在 `README.md` 中补充工具边界与自动验证说明
- [ ] 在 `tests/test_tools.py` 中补充 verify_command 工具级测试
- [ ] 在 `tests/test_agent_runtime.py` 中补充 verify_command runtime 测试
- [ ] 设计 `.agent/verify-policy.json` schema
- [ ] 实现 repo policy loader 与 matcher
- [ ] 增加 verify 专用 observability 事件
- [ ] 增加 `tests/test_verify_policy.py`
- [ ] 评估基于变更文件映射最小验证集的增强方案


---

## 当前实现状态（第二轮后）

### 已完成

- [x] 新增 `verify_command` 工具，并保持 `exec` 为审批兜底
- [x] 支持 Go / Python / TypeScript 常见验证命令
- [x] 支持仓库级策略文件路径 `.agent/verify-policy.json`
- [x] README 已同步 verify 配置与使用边界
- [x] 已补默认 `.agent/verify-policy.json` 示例文件，便于仓库快速定制规则
- [x] 已增加 verify 专属可观测性事件：
  - `verify.execution.requested`
  - `verify.execution.completed`
  - `verify.execution.rejected`

### 本轮落地说明

当前实现中，`verify_command` 在进入执行前会记录 `verify.execution.requested`。当命令通过校验并执行完成后，会记录 `verify.execution.completed`；当命令因 shell token、语言限制、cwd/path 越界、仓库策略不匹配、策略文件格式错误等原因被拒绝时，会记录 `verify.execution.rejected`。

这些事件与现有的 `tool.execution.completed` 并存：

- verify 事件用于描述 `verify_command` 的专属判定与执行阶段；
- tool 事件继续保留通用工具层审计语义。
