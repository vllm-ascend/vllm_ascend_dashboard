# 问题定位页面重新设计 — 实现方案

> Issue: https://github.com/vllm-ascend/vllm_ascend_dashboard/issues/170

## 目标

重新设计「问题定位」页面，统一支持 PR 流水线问题定位和 Nightly Job 问题定位，用户输入 PR 编号或选择失败的 Nightly Job，LLM 分析后给出诊断报告。

## 现状分析

| 功能 | 位置 | 模式 | 流式 |
|------|------|------|------|
| CI Job 失败诊断 | /issue-diagnosis | 选择失败 Job | SSE 流式 |
| Commit 代码分析 | /issue-diagnosis | 选择 Commit | SSE 流式 |
| 手动输入 | /issue-diagnosis | 粘贴日志 | SSE 流式 |
| PR 诊断 | /pr-pipeline/{n} (PR详情页) | 输入 PR 编号 | 非流式 JSON |

问题：PR 诊断独立在 PR 详情页，未统一到问题定位页面。

## 设计方案

### 数据源类型调整

```
旧: ci_job / commit / manual
新: pr_pipeline / ci_job / manual
```

- 新增 `pr_pipeline` — 用户输入 PR 编号
- 移除 `commit` — 使用率低，聚焦 PR 和 Nightly Job
- 保留 `ci_job` — Nightly Job 失败诊断
- 保留 `manual` — 手动输入日志

### 前端改动

#### 1. `IssueDiagnosis.tsx` — 页面重构

**数据源选择器** 改为三个选项：
- PR 流水线诊断 (`pr_pipeline`)
- Nightly Job 失败诊断 (`ci_job`)
- 手动输入 (`manual`)

**PR 模式 UI**：Input.Number 输入 PR 编号 + 诊断按钮

**CI Job 模式 UI**：保持现有（失败 Job 下拉选择）

**结果渲染**：统一使用 `StreamMarkdownRenderer`
- PR 模式：非流式，调用 `diagnosePR(prNumber)` 后一次性设置 `streamContent`，`isStreaming=false`
- CI Job 模式：保持 SSE 流式

#### 2. `useIssueDiagnosis.ts` — Hook 扩展

新增状态：
- `prNumber: number | null`

`handleStartDiagnosis` 分支：
- `pr_pipeline` 模式：调用 `diagnosePR(prNumber)`，返回完整报告后设置 `streamContent` + `meta` + `summary`
- `ci_job` 模式：保持现有 SSE 流式
- `manual` 模式：保持现有 SSE 流式

#### 3. `PRDetail.tsx` — 移除独立 AI 诊断

移除 `usePRDiagnosis` hook、`diagnosisResult` 状态、AI 诊断按钮、诊断报告卡片。
PR 诊断统一到问题定位页面。

### 后端改动

**无后端改动**。复用现有端点：
- `POST /api/v1/pr-pipeline/{pr_number}/diagnose` — PR 诊断（非流式）
- `POST /api/v1/issue-diagnosis/diagnose` — CI Job 诊断（SSE 流式）
- `GET /api/v1/issue-diagnosis/data-sources/ci-jobs` — 失败 Job 列表

### 文件清单

| 文件 | 改动 |
|------|------|
| `frontend/src/pages/IssueDiagnosis.tsx` | 重构：新增 PR 模式，移除 Commit 模式 |
| `frontend/src/hooks/useIssueDiagnosis.ts` | 扩展：新增 prNumber 状态 + PR 诊断分支 |
| `frontend/src/pages/PRDetail.tsx` | 精简：移除 AI 诊断相关代码 |

### 不改动

- 后端 API 和 Service 不变
- `StreamMarkdownRenderer` 不变（已支持非流式）
- `services/issueDiagnosis.ts` 不变
- `services/prPipeline.ts` 不变（`diagnosePR` 已存在）

## 测试计划

1. TypeScript 编译通过
2. 前端构建通过
3. 手动验证：
   - PR 模式：输入 PR 编号 → 点击诊断 → 显示报告
   - Nightly Job 模式：选择失败 Job → 点击诊断 → 流式显示报告
   - 手动模式：输入日志 → 点击诊断 → 流式显示报告
   - PR 详情页不再显示 AI 诊断按钮
