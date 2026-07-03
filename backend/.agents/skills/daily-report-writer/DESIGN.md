# 每日报告技能设计文档（PM 视角）

> Skill: `daily-report-writer` (scope: `daily_report`)
> 目标：让看板 LLM 每天自动产出**有内容、有洞察、可行动**的运营日报并邮件推送。

---

## 一、问题诊断：当前报告为什么「没内容、不好看」

经源码追踪与线上验证（issue #135），当前日报空洞有 3 个根因：

| 根因 | 现象 | 代码位置 |
|------|------|----------|
| **邮件报告根本没调 LLM** | `ai_summary_snippet` 只是截取另一个服务（DailySummaryService）生成的 GitHub 动态 markdown 前 300 字 | `daily_report.py:213-219` |
| **LLM 只看 GitHub 数据** | 生成摘要的 prompt 只喂 PR/Issue/Commit，看不到 CI/测试/模型/性能 | `daily_summary.py:718-737` |
| **性能/模型数据源缺失** | `PerformanceData` 表无采集器（恒空）；`ModelReport` 依赖同步配置 | `performance.py:108-114`(stub)、无 PerformanceData 写入 |

结论：**报告不是「格式」问题，是「数据没喂进去 + LLM 没被调用」的架构问题**。光改邮件模板没用，必须让 LLM 真正消费全量看板数据。

---

## 二、PM 设计：Maintainer 需要什么样的日报

### 用户画像
vLLM-Ascend 社区 Maintainer / 项目负责人。每天早上花 30 秒扫一眼邮件，回答三个问题：
1. **项目健康吗？**（CI/测试/模型是否绿灯）
2. **今天我该关注什么？**（哪里失败、谁该处理）
3. **昨天发生了什么？**（重要 PR/Issue 动态）

### 设计原则
- **洞察 > 数据**：Maintainer 不缺数据（看板上有），缺「所以呢」。每段先结论后数据。
- **可行动**：风险项必须带责任人 / PR号 / 链接，能直接处理。
- **可扫读**：emoji 分区 + 健康色标（🟢🟡🔴⚪）+ 加粗关键数字。
- **诚实降级**：数据缺失明示「⚪ 本期无 X 数据」，不留空表、不编造。
- **篇幅克制**：600–900 字，邮件一屏可览。

### 报告结构（8 板块）
1. 📊 一句话总结 — 今日整体状态 + 最需关注的事（必报）
2. 🏥 整体健康度 — 综合评分 + 各维度色标（必报）
3. 🔧 Nightly 流水线 — 仅前一天 23:00 后发起的 CI 任务（**规则适用但不在报告中显示该说明**），成功率/失败/连续失败/耗时，**附趋势图图片**（必报）
4. ☁️ 资源看板昨日运行 — 集群实例/Pod/NPU 利用率，**附过去 24h 趋势图图片**（必报，新增）
5. 🧪 测试质量 — 健康度、失败用例及责任人、Flaky（按需，无数据则省略）
6. 📈 PR 流水线 — Open/合并/积压、长期未处理 PR（按需）
7. 💡 项目动态 — AI 精选 2-4 条重要 PR/Issue/Commit（按需）
8. ⚠️ 今日风险与待办 — 按优先级 2-5 项，带责任人（必报）
9. 📉 性能趋势 — 吞吐/延迟（按需）

> ~~模型验证~~ 暂不纳入日报（功能不成熟，后续启用）。板块顺序固定。必报板块（1-4、8）始终输出；按需板块（5-7、9）当天无数据则**整段省略**，不留空标题、不显「无数据」占位。趋势图以图片形式内嵌（系统生成 PNG，邮件 CID 内嵌）。

---

## 三、数据管道改造：让 LLM 吃到全量数据

### 现状 vs 目标

| 板块 | 现状 | 目标 |
|------|------|------|
| Nightly | ✅ 已采集 `CIResult` | **改窗口**：仅查 `started_at >= 前一天23:00(北京)=前一天15:00 UTC`；补充趋势与连续失败计算 |
| 资源 | ✅ 已采集 `ResourceNpuMetrics`/`ResourceNodeMetrics`（每分钟） | **新增接入日报**：聚合过去 24h 利用率均值/峰值/异常 |
| 测试 | ❌ 未接入日报 | **新增**：从 `TestCase`/`TestRun`/`TestSuiteSnapshot` 聚合 |
| 模型 | ⚠️ 依赖同步配置 | **暂不纳入日报**（功能不成熟）；数据采集保留，后续启用时接入 |
| PR 流水线 | ❌ 未接入日报 | **新增**：从 `PullRequest` 聚合（open/merged/积压/stale） |
| GitHub | ✅ 文件存储 | 复用，但传 highlights 而非全量 |
| 性能 | ❌ 表恒空 | **新增采集器**（见下） |
| 失败诊断 | ❌ 未接入 | **新增**：从 `JobFailureAnalysis` 取已分析的失败摘要 |

### 新增/改造数据采集器（DailyReportService 方法）

1. **`_collect_nightly_data()`** — 查 `CIResult` where `started_at >= (report_date - 1天) 15:00 UTC`（即前一天 23:00 北京时间），算成功率/失败/连续失败/耗时趋势
2. **`_collect_resource_data(24h)`** — 查 `ResourceNpuMetrics`/`ResourceNodeMetrics` 过去 24h，算 NPU/CPU/内存利用率均值/峰值/异常时段
3. **`_collect_test_data(start, end)`** — 查 `TestSuiteSnapshot`（按日）+ `TestCase`（失败/flaky 用例及 owner）
4. **`_collect_pr_data(start, end)`** — 查 `PullRequest`（state/review_status/ci_status/created_at/merged_at，算积压与 stale）
5. **`_collect_failure_analysis(start, end)`** — 查 `JobFailureAnalysis`（problem_category/root_cause，给风险项用）

### 趋势图截图生成（新增，邮件内嵌）

报告需附 2 张趋势图，由后端用 matplotlib 生成 PNG，通过邮件 CID 内嵌：

| 图片 CID | 内容 | 数据源 |
|----------|------|--------|
| `cid:nightly_trend` | Nightly 成功率/运行数 近 7-14 日趋势折线 | `CIResult` 按日聚合 |
| `cid:resource_trend` | 过去 24h NPU/CPU/内存利用率折线 | `ResourceNpuMetrics`/`ResourceNodeMetrics` 按小时聚合 |

实现：`_generate_trend_charts()` 用 matplotlib 渲染 PNG → 保存临时文件 → 邮件用 `aiosmtplib` 的 MIMEMultipart + CID `image` 部分内嵌。LLM 输出中用 `![...](cid:nightly_trend)` 引用，邮件渲染时替换为内嵌图。

### 性能数据采集器（补建，解决恒空）

`PerformanceData` 表无写入路径。两个方案：
- **方案 A（推荐，低成本）**：从 `ModelReport.metrics_json` 提取 throughput/latency 作为性能数据源（模型验证报告已含性能指标），`_collect_perf_data` 改查 `ModelReport`。
- **方案 B（长期）**：新建 `PerformanceCollector` 定时任务，从 CI 性能测试 job 的 artifact 解析写入 `PerformanceData`。

### 聚合后传入 LLM 的 JSON
见 SKILL.md「输入数据契约」。每个板块带 `has_data` 标志；按需板块 `has_data=false` 时 LLM 整段省略。

---

## 四、LLM 调用改造：让邮件报告真正调用 LLM

### 现状
`DailyReportService` 不调 LLM，只截取 DailySummaryService 的 markdown 片段。

### 改造点

#### 1. DailyReportService 新增 LLM 调用
```python
# daily_report.py — generate_report() 内，聚合数据后
from app.services.claude_code_cli import run_with_fallback
from app.services.skill_registry import get_skill_registry

async def _generate_ai_report(self, report_data: dict) -> str:
    """用 daily-report-writer 技能生成报告正文"""
    skill = get_skill_registry().get_skill_by_scope("daily_report")
    system_prompt = await self._get_system_prompt("daily_report", skill)
    user_prompt = json.dumps(report_data, ensure_ascii=False, indent=2)
    result = await run_with_fallback(
        prompt=user_prompt,
        provider_config=await self._get_llm_config(),
        system_prompt=system_prompt,
        max_turns=4,
    )
    return result.content
```

#### 2. 注册新 scope（system_config.py）
```python
# get_system_prompt_scope_config() 增加分支
if scope == "daily_report":
    skill = get_skill_registry().get_skill_by_scope("daily_report")
    default = skill.content if skill else "你是一名 vLLM Ascend 项目运营分析师..."
    return ("daily_report_system_prompt", {"default": default}, "每日运营报告生成提示词")
```

#### 3. 邮件正文用 LLM 输出替换截断片段
`build_email_html` 把 `ai_summary_snippet`（300 字截断）替换为 `_generate_ai_report` 的完整 Markdown，渲染为 HTML。

#### 4. Skills 管理页可调优
部署 SKILL.md 后，管理员可在「系统管理 → Skills 管理」查看/刷新技能，在「系统提示词」页（scope=daily_report）覆盖调优，无需改代码。

---

## 五、定时任务修复（解决 16 天中断，#135）

当前日报定时任务（08:30）疑似未运行。排查与修复：
1. 确认 apscheduler `daily_report_task` job 存在且 `REPORT_ENABLED=True`
2. 检查 `_send_daily_report_job` 是否被 broad except 吞异常未落库（参考 #131 模式）
3. 邮件 SMTP 失败应落 `status=failed` 记录（历史可见），无记录 = 任务未触发

---

## 六、交付物

| 文件 | 说明 |
|------|------|
| `backend/.agents/skills/daily-report-writer/SKILL.md` | 技能本体（系统提示词），含输出模板/写作原则/数据契约 |
| 本文档 | PM 设计 + 数据管道改造 + LLM 调用 wiring |

### 落地步骤（建议提 PR）
1. 合入 SKILL.md（注册 `daily_report` scope）
2. DailyReportService 新增 `_collect_test_data` / `_collect_pr_data` / `_collect_failure_analysis`，`_collect_perf_data` 改查 ModelReport
3. DailyReportService 新增 `_generate_ai_report`，`generate_report` 调用之
4. `system_config.py` 注册 `daily_report` scope 分支
5. 邮件模板 `daily_report.html` 渲染完整 Markdown（支持 emoji/色标）
6. 修复定时任务中断（#135）
7. 部署后手动触发一次，验证报告内容丰富度

### 预期效果对比
| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| AI 内容 | GitHub 动态前 300 字截断 | 全量看板数据生成的 8 板块洞察 |
| 性能板块 | 恒 null | 从 ModelReport 提取（方案A） |
| 测试板块 | 无 | 失败用例+责任人+Flaky |
| 风险待办 | 无 | 2-5 项带责任人的行动项 |
| 健康度 | 无 | 综合评分+色标 |
| 可读性 | 空表格 | emoji 分区、可扫读 |
