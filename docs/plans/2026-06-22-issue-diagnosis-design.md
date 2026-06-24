# 问题自动定位（Issue Diagnosis）功能设计

日期：2026-06-22

## 需求概述

管理员及以上账号登录系统后，在CI Board中对失败的Job点击"问题定位"按钮，弹出诊断Modal，通过系统配置的LLM API + 自动匹配的Skill，结合用户补充的提示词，流式输出AI根因分析结果。

### 核心决策

| 项目 | 决策 |
|------|------|
| 场景 | CI失败自动根因分析 |
| 交互形式 | 一次性提交 + SSE流式响应 |
| 数据来源 | CI Job（自动填充） + Commit（可选） + 手动输入提示词 |
| Skill | 自动匹配（CI Job → auto-bug-fixer） |
| 入口 | 嵌入CI Board，失败Job的"问题定位"按钮 → 弹出Modal |
| 结果存储 | 仅展示不存储 |
| 权限 | admin 及以上 |

## 架构设计

### 后端新增

**文件：**
- `backend/app/api/v1/issue_diagnosis.py` — API路由
- `backend/app/services/issue_diagnosis.py` — 核心诊断服务
- `backend/app/schemas/issue_diagnosis.py` — Pydantic schemas
- `backend/app/services/llm_client.py` — 新增`generate_stream`流式方法

**API端点：**

| 端点 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/v1/issue-diagnosis/diagnose` | POST (SSE) | admin+ | 提交诊断请求，流式返回结果 |
| `/api/v1/issue-diagnosis/data-sources/ci-jobs` | GET | admin+ | 获取可选择的失败CI Job列表 |
| `/api/v1/issue-diagnosis/data-sources/commits` | GET | admin+ | 获取可选择的commit列表 |

**SSE流式响应格式：**

```
event: chunk
data: {"content": "部分内容..."}

event: meta
data: {"model": "claude-sonnet-4", "provider": "anthropic"}

event: done
data: {"total_tokens": 1234, "duration": 15.2}

event: error
data: {"message": "错误信息"}
```

**流式LLM调用：**

- 直接使用SDK streaming API（不使用Claude Code CLI，CLI不支持流式）
- `OpenAIClient.generate_stream()`: `client.chat.completions.create(stream=True)`
- `AnthropicClient.generate_stream()`: `client.messages.stream()`
- `QwenClient.generate_stream()`: 同OpenAI格式
- 返回 `AsyncGenerator[str, None]`，每次yield一个text chunk

**数据源采集：**

| 数据源 | 采集逻辑 | 来源 |
|--------|----------|------|
| `ci_job` | 复用`FailureAnalysisService._build_job_context()`逻辑 | CIJob + annotations + historical runs |
| `commit` | 从GitHub API获取commit diff | CIResult + GitHub compare |
| `manual` | 直接使用用户输入的文本 | 用户提示词 |

**Skill匹配：**

- CI Job → `auto-bug-fixer` (scope=ci_failure_analysis)
- Commit → 通用commit分析提示词
- Manual → 通用诊断提示词

### 前端新增

**文件：**
- `frontend/src/pages/CIBoard.tsx` — 修改，增加"问题定位"按钮
- `frontend/src/pages/JobDetail.tsx` — 修改，增加"问题定位"按钮
- `frontend/src/components/IssueDiagnosisModal.tsx` — 诊断Modal组件
- `frontend/src/services/issueDiagnosis.ts` — API服务
- `frontend/src/components/StreamMarkdownRenderer.tsx` — 流式Markdown渲染组件

**UI流程：**

```
CI Board → 失败Job → 点击[问题定位]按钮
                → 弹出诊断Modal (宽度80%, 两栏布局)
                → 左栏：数据源信息预览 + 补充提示词TextArea
                → 右栏：流式渲染的AI分析结果 (StreamMarkdownRenderer)
                → [开始诊断] → SSE流式输出 → 结果展示 + [复制] [导出MD]
```

**SSE消费：**
使用原生 `fetch` + `ReadableStream`（POST请求+Bearer认证，EventSource不支持POST+自定义Header）

### 权限控制

- 后端：所有 `/issue-diagnosis` 端点使用 `CurrentAdminUser` 依赖注入
- 前端："问题定位"按钮仅 admin/super_admin 可见

## 不涉及的变更

- 不新增数据库表
- 不修改 skill_registry（只读取）
- 不修改 AISummaryTab（独立渲染组件）
- 不使用 Claude Code CLI（不支持流式）

## 实现计划概要

### Phase 1: 后端核心

1. `llm_client.py` 新增 `generate_stream()` 方法（三个provider的streaming实现）
2. `schemas/issue_diagnosis.py` 定义请求/响应schema
3. `services/issue_diagnosis.py` 实现数据源采集 + Skill匹配 + SSE流式诊断
4. `api/v1/issue_diagnosis.py` 注册路由
5. `main.py` 注册router

### Phase 2: 前端核心

1. `services/issueDiagnosis.ts` API服务 + SSE消费逻辑
2. `components/StreamMarkdownRenderer.tsx` 流式Markdown渲染
3. `components/IssueDiagnosisModal.tsx` 诊断Modal（两栏布局）
4. 修改 `CIBoard.tsx` 和 `JobDetail.tsx` 增加"问题定位"按钮（仅admin可见）

### Phase 3: 测试与验证

1. 验证SSE流式响应正常工作
2. 验证各数据源采集正确
3. 验证权限控制
4. 验证错误处理（LLM不可用、token超限等）
