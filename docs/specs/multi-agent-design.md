# vLLM Ascend 看板 · 多 Agent 协作方案

> 基于 OpenCode 原生 SubAgent 机制，为本仓库定制的「调度总管 + 6 类专项子 Agent」协作方案。
> 单机 / 本地仓库开箱即用，无需额外中间件。

## 一、设计背景与适配要点

本方案基于通用 OpenCode 多 SubAgent 模板，针对 **vLLM Ascend 社区看板** 仓库做了以下关键适配：

| 维度 | 通用模板假设 | 本仓库实情 | 适配做法 |
|---|---|---|---|
| 项目阶段 | 从零搭建新项目 | 已成熟增量维护 | 面向「需求→开发→测试→交付」增量迭代，非全量生成 |
| 技术栈 | 单一 | 全栈：FastAPI(Py) + React(TS) | 编码 Agent 拆为 `backend-coder` + `frontend-coder` 两个多实例 |
| 隔离机制 | `workspace/feature_branches/` | 已有 git worktree（`.worktrees/`）+ issue 分支 | 复用现有 worktree，不另建 workspace |
| 架构产出 | `.opencode/specs/` | 已有 `docs/`（requirements/technical_design/plans） | 新建 `docs/specs/`，与现有文档平级 |
| 测试/CI 产出 | `.opencode/test_reports/` 等 | 已有 `.test-evidence/`、`deploy/`、`.github/workflows/` | 复用现有目录，不新增顶层 |
| 工作流 | 流水线生成交付包 | git 分支 + PR | 不打包 zip，按 feature 分支交付 |

## 二、对模板的字段纠偏

模板中部分字段在 OpenCode 官方 schema 中**不存在**，已用真实等价机制替换：

| 模板字段 | 真实性 | 等价实现 |
|---|---|---|
| `singleton: true/false` | ❌ 不存在 | 主调度 prompt 约束「每轮只调 1 次」+ `.opencode/state/progress.json` 断点续跑 |
| 顶层 `glob: {write, read}` | ❌ 不存在 | `permission.edit` 的 glob→action 对象（`*:deny` 在前，具体 `allow` 在后，last-match-wins） |
| `task.maxParallelSubagents` | ❌ 不存在 | 主调度 prompt 声明并发上限 ≤ 4，分批发起 task |
| `task.subagentTimeout` | ❌ 不存在 | 由 `steps` 限制单 Agent 迭代次数 |
| `mode: primary/subagent` | ✅ 真实 | 直接使用 |
| `permission.task` glob | ✅ 真实 | 控制 primary 可调用的 subagent 白名单 |

> 配置格式以 [OpenCode 官方文档](https://opencode.ai/docs/agents/) 为准。

## 三、目录结构

```
vllm_ascend_dashboard/
├── opencode.json                          # 顶层配置：model / instructions / default_agent
├── .opencode/
│   ├── agents/                            # 7 个 Agent 配置（文件名 = 调用名）
│   │   ├── dispatch_orchestrator.md       # 主调度（primary，默认）
│   │   ├── arch.md                        # 架构（subagent，单例语义）
│   │   ├── backend-coder.md               # 后端编码（subagent，多实例）
│   │   ├── frontend-coder.md              # 前端编码（subagent，多实例）
│   │   ├── tester.md                      # 测试质量（subagent，单例语义）
│   │   ├── devops.md                      # 工程效能（subagent，单例语义）
│   │   └── dockb.md                       # 文档知识库（subagent，单例语义）
│   ├── command/                           # 已有：ralph 系列命令（保留兼容）
│   ├── state/                             # 调度状态、DAG、日报（运行时，已 gitignore）
│   └── ...
├── docs/
│   ├── specs/                             # 【新建】架构 Agent 专属产出目录
│   │   ├── prd.md
│   │   ├── architecture.mermaid
│   │   ├── api.yaml
│   │   ├── tech_solution.md
│   │   ├── risk_register.md
│   │   ├── module_dag.json
│   │   └── multi-agent-design.md          # 本文档
│   ├── knowledge/                         # 文档 Agent 知识沉淀
│   ├── requirements.md                    # 已有
│   └── technical_design.md                # 已有
├── backend/                               # backend-coder / tester 工作区
├── frontend/                              # frontend-coder 工作区
├── deploy/                                # devops 工作区
├── .github/workflows/                     # devops 工作区
├── .test-evidence/                        # tester 产出
└── .worktrees/                            # 已有 git worktree（多实例隔离）
```

## 四、Agent 角色清单

| Agent | mode | 实例 | 职责 | 可写目录 | bash |
|---|---|---|---|---|---|
| `dispatch_orchestrator` | primary | 1 | DAG 编排、调度、冲突仲裁、汇总交付 | `.opencode/state/**` | 仅只读 git |
| `arch` | subagent | 单例 | 需求评审、技术方案、API 契约、模块 DAG | `docs/specs/**`、`.opencode/state/**` | deny |
| `backend-coder` | subagent | 多实例 | FastAPI 路由/service/model/schema/test | `backend/app/**`、`backend/tests/**`、`backend/scripts/**` | uv/pytest/ruff/mypy/git |
| `frontend-coder` | subagent | 多实例 | React 页面/组件/services/hooks/types | `frontend/src/**` | pnpm/node/git |
| `tester` | subagent | 单例 | ruff/mypy/pytest + 前端 lint/tsc、门禁 | `.test-evidence/**`、`backend/tests/**` | uv/pnpm/pytest/ruff/mypy |
| `devops` | subagent | 单例 | CI/CD、Docker、部署、依赖、监控 | `deploy/**`、`.github/workflows/**`、`docker-compose*`、`Dockerfile*`、`pyproject.toml`、`package.json` | docker/uv/pnpm/git |
| `dockb` | subagent | 单例 | 变更日志、操作手册、wiki、知识沉淀 | `docs/change_log.md`、`docs/operation_manual.md`、`docs/wiki_sync.md`、`docs/knowledge/**` | deny |

## 五、协作流程（DAG）

```
用户需求
   │
   ▼
[dispatch_orchestrator] 读 progress.json（断点续跑）
   │
   ▼ 阶段1 串行
[arch] ── 产出 docs/specs/{prd, architecture, api, tech_solution, risk_register, module_dag}
   │   返回 module_dag（backend_modules + frontend_modules）
   ▼ 阶段2 并行（同时 ≤4 实例，按 deps 排批）
[backend-coder ×N] ┐
[frontend-coder ×M]┘ ── 各自 feature 分支，写 .opencode/state/code_{module}.md
   │
   ▼ 阶段3 串行
[tester] ── ruff/mypy/pytest + 前端 lint/tsc → .test-evidence/{summary, bug_list, gate}
   │   gate.blocked=true? → 回退阶段2（最多1次）
   ▼ 阶段4 串行
[devops] ── CI/Docker/部署/依赖 → deploy/、.github/workflows/、docker-compose*
   │
   ▼ 阶段5 串行
[dockb] ── 文档归档 → docs/{change_log, operation_manual, wiki_sync, knowledge/}
   │
   ▼ 阶段6 汇总
[dispatch_orchestrator] → .opencode/state/{task_split.md, dag_flow.mermaid, daily_report.md, progress.json}
   │
   ▼
向用户输出：产出清单 + 日报摘要 + 遗留风险
```

## 六、关键机制

### 1. 权限隔离（防冲突）
每个 Agent 的 `permission.edit` 用 glob→action 对象限定可写目录，`*:deny` 在前、具体 `allow` 在后（OpenCode 规则：**last matching rule wins**）。越权写入会被拦截。

### 2. 单例语义（无 singleton 字段的等价实现）
- 主调度 prompt 明确「`arch`/`tester`/`devops`/`dockb` 每轮只调 1 次」
- `.opencode/state/progress.json` 记录各阶段完成状态，重启时跳过已完成阶段
- 重复调用时，单例 Agent 先读已有产出，只做增量修订

### 3. 多实例并行（编码 Agent）
- `backend-coder`/`frontend-coder` 可被多次 task 调用，每次独立子会话
- 主调度分批发起，同时运行 ≤4，先发 4 个，有返回再发下一个
- 每实例在独立 git worktree/feature 分支工作（`.worktrees/`），文件级隔离

### 4. 断点续跑
`progress.json` 结构：
```json
{
  "session_id": "...",
  "requirement": "用户需求摘要",
  "phases": {
    "arch": {"status": "done", "module_dag": {...}},
    "code": {"status": "done", "modules": [...]},
    "test": {"status": "done", "gate": "pass"},
    "devops": {"status": "pending"},
    "doc": {"status": "pending"}
  }
}
```
主调度启动时先读它，从第一个 `pending` 阶段续跑。

### 5. 冲突仲裁
- 契约冲突 → 以 `docs/specs/api.yaml` 为准，偏离方回退
- 文件冲突 → arch 裁决归属
- 质量分歧 → **tester 一票否决**
- 范围越权 → permission.edit 拦截 + 记录

## 七、使用方式

### 方式 1：全自动流水线（推荐）
1. 打开 OpenCode，默认即 `dispatch_orchestrator`（已在 opencode.json 设 `default_agent`）
2. 输入需求，例如：
   > 为 CI 看板新增「按 NPU 型号分组的成功率趋势」功能
3. 主调度自动执行 6 阶段流水线，结束后查看 `.opencode/state/daily_report.md`

### 方式 2：手动单调（调试 / 临时）
在对话中 `@` 调用单个子 Agent：
```
@arch 重新设计 XXX 模块的接口契约
@backend-coder target_module=infer_core 单独实现后端
@tester 只跑后端 pytest 并出报告
@devops 更新 CI 加一个前端构建 job
```

### 会话导航
- `Tab` 切换 primary agent
- `<Leader>+Down` 进入子 Agent 子会话
- `<Leader>+Left/Right` 切换并行子会话
- `<Leader>+Up` 返回主调度

## 八、与现有基础设施的集成

| 现有设施 | 集成方式 |
|---|---|
| `.pre-commit-config.yaml`（ruff/mypy/hooks） | tester 直接调用 `uv run ruff/mypy`，与 pre-commit 一致 |
| `verify_*.py`、`diagnose_ci.py`、`perf_check.py` | tester/devops 可调用这些既有校验脚本 |
| `.worktrees/` git worktree | backend-coder/frontend-coder 多实例在各自 worktree 工作 |
| `.opencode/command/ralph-*.md` | 保留兼容，不冲突 |
| `docs/requirements.md`、`docs/technical_design.md` | 通过 `opencode.json.instructions` 全局加载，所有 Agent 共享上下文 |
| issue/feature 分支工作流 | coder 在 feature 分支提交，符合现有 PR 流程 |

## 九、避坑指南

| 问题 | 解决 |
|---|---|
| SubAgent 无法被调度调用 | 检查 `dispatch_orchestrator` 的 `permission.task` 是否 `allow` 了对应 agent 名；确认 `.md` 文件名无空格、`mode: subagent` |
| 多个 coder 改同一文件冲突 | `permission.edit` glob 已隔离；有依赖的模块由 arch 在 `module_dag.deps` 标注，主调度串行排批 |
| 单例 Agent 被重复执行 | 主调度读 `progress.json` 跳过已完成阶段；Agent 自身先读已有产出 |
| 并行过多机器卡顿 | 主调度 prompt 限制同时 ≤4 实例；可手动改 prompt 降到 2 |
| `permission.edit` glob 不生效 | 确认 `*:deny` 在前、具体 `allow` 在后（last-match-wins）；路径相对项目根 |
| 子 Agent 越权写文件 | 被 `permission.edit` 拦截，记录到 `.opencode/state/failures.log`，主调度让其重试 |

## 十、文件清单

本方案新增/修改的文件：

| 文件 | 说明 |
|---|---|
| `opencode.json` | 顶层配置（model、instructions、default_agent） |
| `.opencode/agents/dispatch_orchestrator.md` | 主调度 Agent |
| `.opencode/agents/arch.md` | 架构 Agent |
| `.opencode/agents/backend-coder.md` | 后端编码 Agent |
| `.opencode/agents/frontend-coder.md` | 前端编码 Agent |
| `.opencode/agents/tester.md` | 测试质量 Agent |
| `.opencode/agents/devops.md` | 工程效能 Agent |
| `.opencode/agents/dockb.md` | 文档知识库 Agent |
| `docs/specs/multi-agent-design.md` | 本文档 |
| `.gitignore` | 追加忽略 `.opencode/state/` 等运行时产物 |
