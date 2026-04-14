# 代码修改后自动验证执行方案调研

## 当前项目现状

项目当前已经将本地能力拆分为多类工具，并明确了工具边界：

- `read_file`：读取具体文件内容，免审批。
- `inspect_path`：`pwd/ls/find/du` 风格路径检查，免审批。
- `read_only_command`：仅允许 `head/tail/wc/stat/file` 的超窄只读命令，免审批。
- `git_inspect`：只读 git 检查，免审批。
- `git_run`：较宽泛的 git 执行，需要审批。
- `exec`：任意 shell 执行，需要审批。

这一结构已经说明项目的基本安全哲学：

1. **优先使用语义清晰、范围收窄的工具**，而不是泛化 shell。
2. **审批与否不由“用户是不是常用”决定，而由副作用边界决定**。
3. **通过 tool description + execute-time validation 双层约束**来引导与兜底。
4. `exec` 已被刻意收窄为“最后兜底”，而不是默认执行面。

这对“代码改完后自动跑测试/验证命令”是一个非常好的基础，因为这类需求本质上也是：

- 用户希望减少确认打断；
- 但不能把任意 shell 直接放开；
- 需要新增一个**比 `exec` 更窄、但比 `read_only_command` 更强**的执行层。

## 当前实现里和本问题直接相关的关键点

### 1. 工具注册与审批模型是静态可扩展的
`agent/tools/registry.py` 当前通过 `build_tools(...)` 注册工具，默认工具集已经固定列出。说明新增一个 `verify_command` / `safe_exec` 类工具的成本很低，且符合当前项目架构。

### 2. 运行时审批模型支持“某类工具默认免审批”
`agent/runtime/agent.py` 中，tool 是否需要审批由 `tool.requires_approval` 决定。也就是说，新增一个默认免审批但强校验的验证工具，不需要改动整体交互范式，只需要：

- 新增工具；
- 把 `requires_approval = False`；
- 在 `execute(...)` 中实现严格校验。

这和当前 `read_only_command` 的做法完全一致。

### 3. 现有 `read_only_command` 已经提供了一个重要模式
`read_only_command` 的实现提供了几个值得复用的设计模式：

- 使用 `shlex.split(...)` 解析参数；
- 先做 `_validate_args(...)`，再执行；
- 明确拒绝 shell composition token（`|`, `&&`, `;`）；
- 对路径做 `resolve_path(...)`，限制在 workspace；
- 对不同命令做子规则验证。

这意味着如果要做“自动测试/验证命令”，最自然的做法不是扩展 `exec`，而是**沿用 `read_only_command` 的结构，新建一个专门的受限执行工具**。

### 4. 当前 `exec` 的描述已经不适合承载“自动验证”
`exec_tool.py` 的 description 明确写了：

- 仅用于更窄工具覆盖不到的情况；
- 它总是需要审批。

如果强行往 `exec` 里加入“某些命令免审批”的特殊分支，会破坏当前边界的可解释性：

- LLM 很难准确判断何时走 `exec` 的免审批分支；
- 人类也难以从描述理解“为什么同样是 exec，有时候要审批、有时候不要”；
- 测试与审计会更复杂。

因此，从当前项目架构出发，**不要在 `exec` 内混入免审批验证逻辑**，而应新增专用工具。

## 问题本质

用户需求不是“放开 shell”，而是：

> 对代码修改后常见的验证/测试/构建命令提供自动执行能力，同时尽量不引入高副作用、高逃逸性、高外部交互风险。

这类命令和当前 `read_only_command` 最大的不同在于：

1. 它们通常不只读，可能会产生临时构建产物、缓存、测试报告。
2. 它们经常是语言/生态特定的：go、python、npm、cargo、make 等。
3. 有些命令表面是“验证”，实际可能带来网络访问、依赖安装、执行任意脚本等风险。
4. 用户希望“常用验证免确认”，但不同 repo 的“正确验证方式”并不相同。

因此，不能用“只要是 test/build/lint 字样就放行”的简单规则，必须做更细分的方案设计。

## 候选设计方向

### 方案一：继续使用 `exec`，只是在 policy 层给部分命令放行

#### 形式
保留单一 `exec` 工具，但把审批策略改成：

- `exec` 默认审批；
- 若命令命中 allowlist（例如 `go test ./...`、`python -m pytest`），则免审批；
- 否则仍审批。

#### 优点
- 改动表面最少；
- 不需要增加新 tool；
- 对 CLI 用户来说概念数量少。

#### 缺点
- 破坏现有工具边界哲学，`exec` 语义混乱；
- LLM 很容易仍旧把很多验证命令走到 `exec`，导致行为不透明；
- 审批规则与工具语义分离，阅读和维护成本高；
- 测试矩阵会变复杂：同一工具既要测审批又要测免审批路径；
- 审计时很难从事件名看出这是“安全验证执行”还是“任意 exec”。

#### 结论
从当前项目结构看，这个方案**实现快，但长期最差**，不推荐作为最终方案。

### 方案二：新增 `verify_command` 工具，内置通用 allowlist

#### 形式
新增一个专门工具，例如：

- `verify_command`
- 或 `safe_verify`
- 或 `project_check`

只允许执行“修改代码后的验证、测试、lint、build”命令。该工具默认免审批，但执行前做严格校验。

#### 核心特点
- 输入应尽量结构化，例如 `argv: ["go", "test", "./..."]`，而不是原始 shell。
- 禁止 shell 组合与重定向。
- 只允许有限程序与子命令组合。
- 限制 cwd 必须在 workspace。
- 默认禁止 install/publish/deploy/network/script execution。
- 对执行时间、输出长度、路径范围做限制。

#### 优点
- 和当前项目的“窄工具优先”原则高度一致；
- 工具语义清晰，模型更容易选对；
- 默认免审批的边界可解释；
- 易于增加专门测试与审计事件；
- 可逐步扩展支持语言生态。

#### 缺点
- 通用 allowlist 一开始需要人工设计；
- 不同项目的验证命令差异较大，纯内置规则会不够灵活；
- `npm run <script>` 这类场景，如果只看命令名仍可能带来脚本副作用问题。

#### 结论
这是**最稳妥的基础方案**，但如果只做内置 allowlist，后续会遇到多项目适配瓶颈。

### 方案三：新增 `verify_command` + 项目级策略文件

#### 形式
在方案二基础上，再增加仓库内策略文件，例如：

- `.agent/verify-policy.json`
- 或 `agent.verify.yaml`

自动执行必须同时满足：

1. 命中平台内置安全规则；
2. 命中当前 repo 的本地允许规则。

#### 本地策略可描述的内容
- 允许哪些命令模板；
- 允许哪些 `npm run` script 名；
- 每个命令的 timeout；
- 允许的 cwd 范围；
- 允许的路径参数模式；
- 是否允许 build；
- 是否允许生成临时工件；
- 针对该 repo 的推荐验证命令。

#### 例子
Python 项目可以允许：
- `python -m unittest discover -s tests`
- `python -m unittest tests.test_agent_runtime`
- `ruff check agent tests`

Go 项目可以允许：
- `go test ./...`
- `go test ./pkg/...`

Node 项目可以允许：
- `npm run test`
- `npm run lint`
- `npm run build`

但 `npm run release`、`npm run publish` 不允许。

#### 优点
- 兼顾平台安全与项目差异；
- 自动执行边界最可控；
- 用户可以显式声明“本项目哪些命令值得自动跑”；
- 减少模型猜测；
- 很适合作为长期演进方向。

#### 缺点
- 初次接入成本比方案二高；
- 需要设计策略文件 schema；
- 无策略文件的仓库需要有降级策略。

#### 结论
这是**长期最佳方案**。

### 方案四：命令风险评分 + 阈值自动执行

#### 形式
不采用简单 allowlist，而是对命令做风险打分：

- 是否含 shell token；
- 是否调用脚本解释器；
- 是否含网络操作；
- 是否会修改依赖；
- 是否会运行 package script；
- 是否可能越界路径。

分数低于阈值自动执行，高于阈值审批。

#### 优点
- 理论上更灵活；
- 可以减少大量静态规则维护。

#### 缺点
- 可解释性差；
- 边界不稳定；
- 容易出现“看似低风险、实际危险”的漏判；
- 很难写出让 LLM 和人都稳定理解的规则；
- 对当前项目这种强调窄边界的架构不够匹配。

#### 结论
更适合作为远期增强，不适合作为第一阶段方案。

## 对不同生态的风险观察

### Python
相对最容易做受控验证：
- `python -m unittest`
- `python -m pytest`
- `ruff check`
- `mypy`

主要风险：
- `python script.py` 实际可执行任意本地逻辑；
- `python -m pip install` 会联网/改依赖；
- pytest fixture 可能触发外部资源访问，但这更接近项目测试本身的风险。

### Go
也较适合：
- `go test` 通常语义清晰。

主要风险：
- `go run` 可执行任意程序；
- `go generate` 可能执行脚本；
- 某些测试可能联网。

### npm / pnpm / yarn
风险最高。

因为：
- `npm run test` 背后是 package.json 中任意 script；
- script 可以链式执行任意 shell；
- `npm run build` 也可能带副作用；
- `npm install` / `npm exec` / `npx` 风险更高。

因此 Node 生态更适合采用：
- 项目策略文件显式允许具体 script 名；
- 或进一步读取 package.json 校验 script 内容是否符合安全模式。

### make
风险中高。

`make test` / `make lint` 很常见，但 Makefile 本质上也能运行任意 shell。若允许 make，建议：
- 只允许非常具体的 target 名；
- 最好仍结合项目策略文件；
- 必要时对目标内容做静态检查。

## 关键设计原则

### 1. 不要把“常用”误当成“安全”
很多命令虽然高频，但并不低风险，例如：
- `npm run build`
- `make test`
- `python script.py`

是否可自动执行，应该取决于：
- 是否属于项目内验证意图；
- 是否可结构化校验；
- 是否能证明没有明显高危副作用；
- 是否被项目策略显式允许。

### 2. 不要接收原始 shell 字符串作为主接口
如果做新工具，最佳接口应是：

```json
{
  "argv": ["go", "test", "./..."],
  "reason": "validate refactor"
}
```

而不是：

```json
{
  "command": "go test ./..."
}
```

结构化 `argv` 有几个明显好处：
- 避免 shell 解析歧义；
- 更容易做 denylist / allowlist；
- 更适合审计；
- 更不容易受 provider tool-call 截断影响。

### 3. 自动执行与任意执行必须是两个工具
对当前项目来说，最重要的不是“能不能做”，而是“边界是否清晰”。

因此应保持：
- `verify_command`：默认免审批，但非常窄；
- `exec`：始终审批，宽而危险。

这比在一个工具里塞条件分支更稳。

### 4. 自动执行失败时不能静默降级到 `exec`
如果 `verify_command` 不允许某命令，不应偷偷切换为 `exec` 并执行。正确行为应该是：
- 直接返回“该命令超出自动验证范围，需要人工审批”；
- 由 LLM 再决定是否请求 `exec`。

否则会把自动执行边界逐渐冲垮。

### 5. 应当有专门的审计事件
当前 observability 已有 event logging，很适合扩展：
- `verify.execution.requested`
- `verify.execution.completed`
- `verify.execution.rejected`

这样可以事后分析：
- agent 最常跑哪些验证命令；
- 哪些命令经常被拒绝；
- 是否需要扩策略；
- 是否出现了异常风险模式。

## 最可行的阶段性落地路线

### 第一阶段
新增 `verify_command`，只支持最小核心集：

- Python：`python -m unittest`、`python -m pytest`、`pytest`、`ruff check`、`mypy`
- Go：`go test`
- Node：`npm run test`、`npm run lint`、`npm run build`

并强制：
- 输入使用 `argv`；
- 禁止 shell token；
- 禁止 install/publish/deploy/network 工具；
- 限制 cwd 在 workspace；
- 限制 timeout / 输出；
- 默认免审批。

### 第二阶段
引入 `.agent/verify-policy.json`，把项目差异外置。

### 第三阶段
让 agent 根据 diff / 项目类型自动选择“最小验证集合”，但仍只在 allowlist 范围内执行。

## 结论
从当前代码结构和已形成的安全策略出发，最合理的方向不是放宽 `exec`，而是：

1. **新增专用的 `verify_command` 工具**；
2. **默认免审批，但比 `exec` 窄得多**；
3. **采用结构化 `argv` 输入，不接收原始 shell**；
4. **短期使用内置 allowlist，长期叠加项目级策略文件**；
5. **保留 `exec` 作为必须审批的最终兜底通道**。

这与项目现有的 `read_only_command` / `inspect_path` / `git_inspect` / `exec` 边界收敛思路完全一致，是最自然、最稳定的演进方向。
