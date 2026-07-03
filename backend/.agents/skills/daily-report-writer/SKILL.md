---
name: daily-report-writer
description: Use when generating the vLLM Ascend daily operations report email — produces an insight-driven, scannable digest of CI health, test quality, model validation, PR pipeline and project activity from aggregated dashboard data
scope: daily_report
---

# 每日运行报告撰写技能

## 概述
将看板聚合数据（CI / 测试 / 模型 / PR 流水线 / GitHub 动态 / 失败诊断 / 性能）转化为一份**可扫读、有洞察、可行动**的每日运营报告，供社区 Maintainer 用 30 秒掌握项目健康度并知道今天该关注什么。

**核心原则：报告价值在于洞察与行动，而非数据堆砌。内部所有人均可随时查看实时看板，管理者、Maintainer 不缺原始指标，缺失的是指标背后的结论：今日异常点、根因判断、责任归属、恶化趋势、闭环动作。日报禁止罗列原始大盘数据，只输出问题、洞察、风险、待办。

## 使用场景
- 每日 08:30 定时任务触发，生成昨日（北京时间）运营报告
- 管理员在「每日报告」页手动触发指定日期报告
- 输入为系统聚合的结构化 JSON（见「输入数据契约」），输出为 Markdown 报告正文

## 写作原则（必须遵守）

| 原则 | 要求 | 反模式（禁止） |
|------|------|----------------|
| **洞察优先** | 每个板块先给一句话结论，再给数据佐证 | 罗列数字不给解读 |
| **可行动** | 风险项必须带责任人/PR号/链接，能直接处理 | 只说「有失败」不说谁负责 |
| **可扫读** | emoji 分区 + 健康色标 + 加粗关键数字 + 列表 | 大段散文 |
| **按需通报** | 核心板块（Nightly/资源/健康度/风险）必报；其余板块当天无数据则**整段省略**，不留空行、不显示「无数据」占位 | 用 null/0 充数、留空白板块、编造数据 |
| **趋势导向** | 有历史对比时给出 ↑↓ 变化，比绝对值更有意义 | 只报当日绝对值 |
| **篇幅克制** | 全文控制在 600–900 字，重点突出 | 长篇大论、复制原始日志 |

## 健康度色标规范
- 🟢 良好：通过率≥95% / 无连续失败 / 积压<1.5天
- 🟡 需关注：通过率 80–95% / 个别失败 / 积压 1.5–3天
- 🔴 需介入：通过率<80% / 连续失败≥2 / 积压>3天 / 关键模型失败
- ⚪ 无数据：该维度当日无数据

## 输出格式（核心板块必报，其余板块当天无数据则整段省略，不留空行）

> 板块顺序固定。标注「必报」的板块始终输出；标注「按需」的板块仅当 `has_data=true` 时输出，无数据时**整段删除**，不输出「⚪ 无数据」占位。趋势图通过 `cid:` 引用邮件内嵌截图（系统生成并附图）。

```
# 📊 vLLM Ascend 每日运行报告 | {{report_date}}

> {{one_sentence_summary}}  ← 一句话总结今日整体状态与最需关注的事

## 🏥 整体健康度（必报）
综合评分：{{grade}} ({{score}}/100) ｜ Nightly：{{ci_badge}}｜资源：{{resource_badge}}
{{#if has_test}}｜ 测试：{{test_badge}}{{/if}}

## 🔧 Nightly 流水线（必报）
**{{conclusion}}**（{{total_runs}} 次运行，成功 {{success}} / 失败 {{failure}}，成功率 {{success_rate}}%）
- 平均耗时 {{avg_duration}}，较 7 日均值 {{trend}}
- {{#if failed_workflows}}失败 workflow：{{failed_list_with_reason}}{{/if}}
- {{#if consecutive_failures}}⚠️ 连续失败：{{consecutive_list}}{{/if}}
![Nightly 成功率趋势](cid:nightly_trend_chart)

## ☁️ 资源看板昨日运行（必报）
昨日集群运行 {{running_instances}} 实例｜执行中 Pod {{running_pods}}｜在用 NPU {{npu_cards}} 卡｜平均利用率 NPU {{npu_util}}% / CPU {{cpu_util}}% / 内存 {{mem_util}}%
- {{#if resource_anomaly}}⚠️ 异常：{{anomaly_list}}{{/if}}
![过去 24 小时资源趋势](cid:resource_trend_chart)

{{#if has_test}}
## 🧪 测试质量（按需）
健康度 {{test_health_score}}/100 ({{test_level}})｜用例 {{total}}｜通过 {{passed}}｜失败 {{failed}}｜Flaky {{flaky}}
- {{#if failed_cases}}失败用例（责任人）：{{failed_cases_with_owner}}{{/if}}
- {{#if attention_cases}}需关注：{{attention_list}}{{/if}}
{{/if}}

{{#if has_pr}}
## 📈 PR 流水线（按需）
Open {{open}}｜已合并 {{merged}}｜已关闭 {{closed}}｜平均合入 {{avg_merge_time}}｜积压指数 {{backlog}}{{backlog_badge}}
- {{#if stale_prs}}长期未处理 PR（≥3天）：{{stale_top3}}{{/if}}
{{/if}}

{{#if has_github}}
## 💡 项目动态（按需）
{{ai_curated_highlights}}  ← AI 精选的 2-4 条重要 PR/Issue/Commit 动态，每条带 ID + 一句价值说明，不复制原始列表
{{/if}}

{{#if has_perf}}
## 📉 性能趋势（按需）
吞吐 {{throughput}} req/s｜P50 {{p50}}ms｜P99 {{p99}}ms（{{perf_trend}}）
{{/if}}

## ⚠️ 今日风险与待办（必报）
{{#if risks}}
{{risk_items}}  ← 按优先级列出 2-5 项，每项格式：[类型] 描述（责任人/链接）
{{else}}
✅ 今日无明显风险
{{/if}}

---
报告由 vLLM Ascend Dashboard 自动生成 | 详细数据见 {{dashboard_url}}
```

## 输入数据契约（系统聚合后传入的 JSON，字段可缺失）

```json
{
  "report_date": "2026-07-01",
  "dashboard_url": "http://123.57.0.174/",
  "charts": {
    "nightly_trend_chart": "cid:nightly_trend_chart",
    "resource_trend_chart": "cid:resource_trend_chart"
  },
  "nightly": {
    "_window": "报告日前一天 23:00（北京时间，UTC+8）后发起的 CIResult，即 started_at >= 前一天15:00 UTC",
    "total_runs": 3, "success": 2, "failure": 1, "success_rate": 66.7,
    "avg_duration_seconds": 14400, "trend_vs_7d": "+5%",
    "failed_workflows": [{"name": "Nightly-A2", "hardware": "A2", "reason": "timeout", "consecutive_failures": 2}],
    "has_data": true
  },
  "resource": {
    "_window": "过去 24 小时",
    "running_instances": 6, "running_pods": 12, "npu_cards": 20,
    "avg_npu_util": 78.5, "avg_cpu_util": 45.2, "avg_mem_util": 62.1,
    "peak_npu_util": 95.0, "anomaly": [{"time": "03:15", "type": "NPU 利用率峰值 98%"}],
    "has_data": true
  },
  "test": {
    "health_score": 99.3, "level": "A",
    "total": 47, "passed": 45, "failed": 2, "flaky": 0,
    "failed_cases": [{"name": "...", "owner": "@xxx", "suite": "Nightly-A3"}],
    "attention_cases": [{"name": "...", "reason": "flaky_rate 30%"}],
    "has_data": true
  },
  "model": {
    "_note": "模型验证暂未纳入日报（功能不成熟），此字段当前不渲染到报告，保留供后续启用",
    "total_reports": 5, "pass": 3, "fail": 2,
    "new_models": ["Qwen3-235B-A22B"], "failed_models": [{"name": "DeepSeek-R1", "reason": "OOM"}],
    "has_data": true
  },
  "pr_pipeline": {
    "open": 336, "merged": 12, "closed": 8,
    "avg_merge_time": "1.2d", "backlog_days": 30.2,
    "stale_prs": [{"number": 10445, "title": "...", "wait_days": 5}],
    "has_data": true
  },
  "github": {
    "pr_count": 40, "issue_count": 18, "commit_count": 20,
    "highlights": ["..."], "has_data": true
  },
  "failure_analysis": {
    "analyzed_failures": [{"job": "Nightly-A2 single-node", "category": "基础设施", "root_cause": "OOM"}],
    "has_data": true
  },
  "performance": {
    "avg_throughput": 1234.5, "avg_p50_latency": 45.2, "avg_p99_latency": 120.0,
    "trend": "↑3%", "has_data": false
  }
}
```

## 工作流程

### 第一步：数据校验与按需通报
- 检查每个板块的 `has_data` 标志
- **必报板块**（健康度/Nightly/资源/风险）始终输出；Nightly 与资源即使数据异常也要说明（如「Nightly 任务未触发」「资源采集异常」）
- **按需板块**（测试/模型/PR/项目动态/性能）`has_data=false` 时**整段省略**，不输出占位行、不留空标题
- 若 Nightly 与资源同时无数据 → 健康度标 ⚪ 并在总结中说明「数据采集可能异常，请检查」
- 不得编造任何未提供的数据

### 第二步：健康度计算与色标
- Nightly 板块：成功率≥95%🟢 / 80-95%🟡 / <80%🔴；连续失败≥2 直接 🔴
- 资源板块：NPU 平均利用率<85%🟢 / 85-95%🟡 / >95%🔴
- 测试板块：health_score≥90🟢 / 75-89🟡 / 60-74🟠 / <60🔴
- 积压指数：<1.5🟢 / 1.5-3🟡 / >3🔴
- 综合评分 = 各维度加权（Nightly 35% + 资源 20% + 测试 25% + PR 12% + 性能 8%），无数据维度不计权重、权重重分配
- 注：模型验证暂未纳入日报（功能不成熟），不参与健康度计算

### 第三步：洞察提炼（核心价值）
- **Nightly**：成功率骤降 / 连续失败 / 耗时异常增长 → 重点提示
- **资源**：NPU 利用率峰值/持续高位 / Pod 异常重启 / 资源争抢 → 重点提示
- **测试**：新增 flaky / 失败用例无责任人 / 健康度下降 → 重点提示
- **PR**：积压恶化 / 长期未处理 PR / 合入放缓 → 重点提示
- 交叉关联：Nightly 失败 + 资源峰值同时段？CI 失败 + 测试失败同源？尽量关联

### 第四步：风险与待办生成
从各板块提取需人工介入的项，按优先级排序（🔴>🟡），每项必须含：
- 类型标签：[Nightly] [资源] [测试] [PR] [性能]
- 一句话描述 + 责任人 / PR号 / 看板链接
- 上限 5 项，避免噪声

### 第五步：输出报告
- 严格按「输出格式」模板渲染，**按需板块无数据则整段省略**
- 趋势图以**图片形式**内嵌报告（Nightly 趋势 + 资源 24h 趋势），由系统生成 PNG 并通过 `cid:` 内嵌，模板中用 `![描述](cid:xxx)` 引用
- 全文 600–900 字，Markdown 格式（邮件客户端兼容）
- 一句话总结放最前，风险待办放显著位置

## 常见错误（禁止）

| 错误 | 正确做法 |
|------|----------|
| 按需板块无数据时输出空标题/「无数据」占位 | **整段省略**，不输出该板块 |
| Nightly 板块纳入 23:00 前的任务 | 仅统计前一天 23:00 后发起的 CIResult |
| 缺少趋势图引用 | Nightly 与资源板块必须含 `![...](cid:...)` |
| 复制原始 PR/Issue 列表 | 精选 2-4 条带价值说明 |
| 风险项无责任人/链接 | 必须带责任人或 PR 号 |
| 用「一切正常」敷衍 | 给具体数字佐证（成功率 X%，Y 用例通过） |
| 超过 900 字 | 删减次要内容，保留洞察与风险 |
| 编造未提供的数据 | 只用输入 JSON 中的字段 |

## 输出末尾必须包含的结构化元数据（供系统解析存档）

```json
{
  "report_date": "2026-07-01",
  "overall_grade": "A",
  "overall_score": 92,
  "top_risks": ["CI:Nightly-A2连续失败", "模型:DeepSeek-R1验证失败"],
  "has_ci": true,
  "has_test": true,
  "has_model": true,
  "has_performance": false
}
```
