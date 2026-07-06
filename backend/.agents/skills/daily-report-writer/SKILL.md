---
name: daily-report-writer
description: Use when generating the vLLM Ascend daily operations report email — produces a positive, systematic community digest covering CI, PR pipeline, model validation, resource dashboard, test board and GitHub activity
scope: daily_report
---

# 每日运行报告撰写技能

## 概述
将看板聚合数据（CI / PR 流水线 / 模型验证 / 资源看板 / 测试看板 / GitHub 动态）转化为一份**正面、系统、可扫读**的社区每日运行报告，让社区 Maintainer 和贡献者用 30 秒了解项目整体进展、昨日成果和需关注事项。

**核心原则：报告是社区的系统日报，既有成果亮点也有风险提示。先讲进展和数据，再讲问题和行动。禁止纯负向描述，每个维度先说结果再说问题。**

## 写作原则

| 原则 | 要求 |
|------|------|
| **正面导向** | 先讲成果（新增PR、合入PR、通过率、利用率），再讲问题。有成绩要报成绩，有进展要报进展 |
| **系统性** | 六大维度（CI/PR/模型/资源/测试/GitHub）均需覆盖，有数据的报数据，无数据的简要说明 |
| **可扫读** | emoji 分区 + 加粗关键数字 + 一句话结论 + 列表 |
| **数据说话** | 每个结论必须有数字佐证（成功率 X%，Y 个 PR 合入，Z% 利用率） |
| **篇幅克制** | 全文 500–800 字，重点突出 |

## 当日健康度规范

**取消月度 SABC 评级，改为当日工程健康度：**

| 状态 | 判定标准 |
|------|----------|
| 🟢 **正常** | CI 成功率≥90% / 测试通过率≥95% / 无关键模型失败 / 资源利用率<90% |
| 🟡 **轻微波动** | CI 成功率 70–90% / 个别测试失败 / 资源利用率 90–95% / 积压轻度上升 |
| 🔴 **高危异常** | CI 成功率<70% / 连续失败≥2 / 关键模型失败 / 资源利用率>95% / 积压严重 |

**相较昨日趋势：回升 / 持平 / 恶化**（基于 last_week 窗口与 yesterday 窗口对比）

## 输出格式

```
# 📊 vLLM Ascend 社区每日运行报告 | {{report_date}}

> {{one_sentence_overview}}  ← 一句话概览：昨日新增XX PR，合入XX，CI成功率XX%，资源利用率XX%，测试通过率XX%，整体健康度【状态】

## ⚡ 当日效能极速概览

当日工程健康度：【正常/轻微波动/高危异常】，相较昨日【回升/持平/恶化】
- CI 流水线：{{ci_status}}（成功率 {{success_rate}}%）
- PR 流水线：新增 {{new_prs}}，合入 {{merged_prs}}，待处理 {{open_prs}}
- 资源利用：NPU 平均 {{npu_util}}%，执行 Pod {{pods}} 个
- 测试质量：通过率 {{pass_rate}}%，Flaky {{flaky}} 个
- 模型验证：{{pass}}/{{total}} 通过
- 正向亮点：{{positive_highlight}}

## 🔧 CI 流水线
**{{conclusion}}**（{{total}} 次运行，成功 {{success}} / 失败 {{failure}}，成功率 {{rate}}%）
- 平均耗时 {{avg_duration}}
{{#if failed_workflows}}
- 失败任务：{{failed_list}}
{{/if}}

## 📈 PR 流水线
昨日新增 {{new_prs}} PR，合入 {{merged_prs}}，关闭 {{closed_prs}}｜当前待处理 {{open_prs}}｜平均合入 {{avg_merge_time}}｜积压指数 {{backlog}}
{{#if backlog_warning}}
- ⚠️ 积压{{backlog_level}}，{{stale_count}} 个 PR 等待≥3天
{{/if}}

## 🧪 模型验证
{{pass}}/{{total}} 通过（通过率 {{pass_rate}}%）
{{#if new_models}}
- 新增模型：{{new_model_list}}
{{/if}}
{{#if failed_models}}
- 失败模型：{{failed_model_list}}
{{/if}}

## ☁️ 资源看板
{{#each clusters}}
- **{{cluster_name}}**：NPU 利用率 {{util}}%（{{used}}/{{total}} 卡），执行 Pod {{pods}} 个
{{/each}}
{{#if resource_anomaly}}
- ⚠️ {{anomaly}}
{{/if}}

## 🧫 测试看板
健康度 {{score}}/100｜用例 {{total}}｜7日通过率 {{pass_rate}}%｜Flaky {{flaky}} 个
{{#if test_issues}}
- {{test_issues}}
{{/if}}

## 💡 社区动态
昨日 {{pr_count}} PR / {{issue_count}} Issue / {{commit_count}} Commit
{{#if highlights}}
- {{highlights}}
{{/if}}

## ⚠️ 需关注事项
{{#if risks}}
{{risk_items}}
{{else}}
✅ 今日各项工作正常推进
{{/if}}

---
报告由 vLLM Ascend Dashboard 自动生成 | 详细数据见 {{dashboard_url}}
```

## 输入数据说明

系统传入的 JSON 包含 `yesterday`、`last_week`、`last_month` 三个时间窗口，每个窗口含以下维度：

```json
{
  "report_date": "2026-07-05",
  "yesterday": {
    "ci": {
      "total_runs": 4, "success_runs": 2, "failure_runs": 2, "success_rate": 50.0,
      "avg_duration_seconds": 14400,
      "failed_workflows": [{"workflow_name": "Nightly-A2", "run_number": 123, "duration_seconds": 14000, "hardware": "A2"}]
    },
    "pr_pipeline": {
      "open_count": 336, "merged_count": 12, "closed_count": 8,
      "backlog_index": 30.2, "backlog_level": "high",
      "merge_rate": 0.3, "avg_time_to_merge_hours": 28.8,
      "recent_opened_count": 5, "recent_merged_count": 3
    },
    "model": {
      "total_reports": 5, "pass_count": 3, "fail_count": 2, "pass_rate": 60.0,
      "new_models": ["Qwen3-235B"], "failed_models": [{"model_name": "DeepSeek-R1", "hardware": "A2", "vllm_version": "0.6"}]
    },
    "resource": {
      "clusters": [
        {"cluster_name": "310P", "avg_npu_utilization": 45.2, "npu_total": 40, "npu_used": 18, "executing_pods": 5},
        {"cluster_name": "A2", "avg_npu_utilization": 78.5, "npu_total": 20, "npu_used": 16, "executing_pods": 8}
      ]
    },
    "test": {
      "health_score": {"overall": 92, "level": "A"},
      "total_cases": 47, "pass_rate_7d": 95.5, "flaky_case_count": 0
    },
    "github": {
      "pr_count": 40, "issue_count": 18, "commit_count": 20, "ai_summary_snippet": null
    },
    "performance": {
      "avg_throughput": 1234.5, "avg_p50_latency": 45.2, "avg_p99_latency": 120.0
    }
  },
  "last_week": { "ci": {...}, "model": {...}, "github": {...}, "performance": {...} },
  "last_month": { "ci": {...}, "model": {...}, "github": {...}, "performance": {...} }
}
```

**字段可能缺失**：resource、test、pr_pipeline 仅在 yesterday 窗口存在。last_week/last_month 仅有 ci/model/github/performance。缺失字段不报、不编造。

## 写作流程

### 第一步：数据汇总
- 从 yesterday 窗口提取六大维度数据
- 从 last_week 窗口提取对比基准（用于趋势判断）
- 缺失维度标记为「暂无数据」，简要说明即可

### 第二步：健康度判定
- CI：成功率≥90%🟢 / 70-90%🟡 / <70%🔴
- 资源：NPU 平均利用率<90%🟢 / 90-95%🟡 / >95%🔴
- 测试：通过率≥95%🟢 / 80-95%🟡 / <80%🔴
- PR：积压<1.5🟢 / 1.5-3🟡 / >3🔴
- 综合：取各维度最差状态作为当日健康度

### 第三步：撰写报告
- **一句话概览**：昨日新增X PR，合入X，CI成功率X%，资源利用率X%，测试通过率X%，健康度【状态】
- **极速概览**：≤200字，浓缩六大维度核心指标 + 正向亮点
- **各维度详情**：先结论后数据，有成绩先报成绩，有问题再报问题
- **需关注事项**：仅列需人工介入的项，无则写「今日各项工作正常推进」

### 第四步：正面亮点提炼
从数据中找出正向信号：
- CI 成功率高 / 较前日提升
- PR 合入效率高 / 积压减少
- 资源利用率合理
- 测试通过率高 / 无 Flaky
- 新模型验证通过
将这些亮点融入极速概览和各维度描述中

## 禁止事项

| 禁止 | 正确做法 |
|------|----------|
| 纯负向描述（"全线崩溃""严重恶化"） | 客观描述数据 + 指出问题（"成功率0%，需排查"） |
| 编造未提供的数据 | 只用输入 JSON 中的字段 |
| 罗列原始数据不给结论 | 先结论后数据 |
| 超过 800 字 | 删减次要内容 |
| 无数据板块留空标题 | 简要说明「暂无数据」即可 |
| 忽略正向信号 | 有成绩必须报成绩 |
