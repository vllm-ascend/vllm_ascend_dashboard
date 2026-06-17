# 资源看板告警规则 — 设计方案

> vLLM Ascend Dashboard · 2026-06

---

## 一、背景与目标

vLLM Ascend Dashboard 的资源看板已具备：

- 多 Kubernetes 集群的 **实时资源监控**（CPU / 内存 / NPU，集群级 + 节点级）
- **NPU 利用率趋势**（历史数据采集、聚合降采样、折线图展示）

但缺少**主动告警能力**。当 NPU 利用率过高、节点资源耗尽等问题出现时，运维人员只能被动查看看板，无法及时响应。

### 目标

- 支持**集群级和节点级**的告警规则
- 支持**多条件组合**（AND / OR / NOT）
- 每条规则可指定**集群范围**（全部集群 / 指定集群 / 指定节点）
- 触发时自动**邮件通知**
- 具备**去重机制**，避免重复告警
- 支持触发**历史查询**

---

## 二、整体架构

```
┌────────────────┐    定时采集（每 1 分钟）
│  K8s Cluster   │────────────────────────────┐
│  (NPU Metrics) │                            │
└────────────────┘                            ▼
                                    ┌──────────────────┐
                                    │  Metric Storage   │
                                    │  resource_npu_    │  ← 集群级时序
                                    │  metrics          │
                                    │  resource_node_   │  ← 节点级时序
                                    │  metrics          │
                                    └──────┬───────────┘
                                           │
                                           ▼
                                    ┌──────────────────┐
                                    │  Alert Evaluator  │  ← 采集后自动评估
                                    │  · 组间 AND       │
                                    │  · 组内 AND/OR    │
                                    │  · NOT 排除       │
                                    └──────┬───────────┘
                                           │ 触发
                                           ▼
                                    ┌──────────────────┐
                                    │  SMTP 邮件通知    │
                                    │  + Alert History  │
                                    └──────────────────┘
```

---

## 三、数据模型

### 三层条件模型

```
alert_rules (规则头)
  ├─ name, cluster_id, node_name, enabled, notify_email
  └─ alert_condition_groups[]     ← 组间 AND
       ├─ logic: "AND" | "OR"
       └─ alert_conditions[]
            ├─ metric_field
            ├─ operator (>, <, >=, <=, ==)
            ├─ threshold
            └─ is_exclude: bool  ← True = NOT
```

### 评估逻辑

```
for rule:
  for group in rule.groups:     ← 组间 AND
    if not evaluate(group):
      → 规则不触发
  → 规则触发，发送告警

evaluate(group):
  if logic == AND: 所有条件满足 → 通过
  if logic == OR:  任一条件满足 → 通过
  is_exclude=True: 条件取反
```

### 语义示例

> **(NPU利用率 > 80 AND 执行中Pod数 > 3) AND (CPU利用率 > 90 OR NOT 节点 == node-a2-01)**

等价于两个条件组，一组 AND，一组 OR 含排除。

---

## 四、支持指标

| 类别 | 指标 | 说明 |
|------|------|------|
| 集群级 | `npu_utilization` | NPU 利用率 (%) |
| | `npu_total` / `npu_used` / `npu_available` | NPU 总量/已用/可用 (卡) |
| | `executing_pods_count` | 执行中 Pod 数 |
| | `pr_count` | 活跃 PR 数 |
| 节点级 | `cpu_utilization` | CPU 利用率 (%) |
| | `memory_utilization` | 内存利用率 (%) |
| | `cpu_cores_used` / `cpu_cores_total` | CPU 已用/总量 (核) |
| | `memory_bytes_used` / `memory_bytes_total` | 内存已用/总量 (GiB) |
| | `npu_utilization` | NPU 利用率 (%) |
| | `npu_total` / `npu_used` / `npu_available` | NPU 总量/已用/可用 (卡) |

---

## 五、去重机制

防止每分钟重复告警：

```
条件首次满足 && 上次未触发 → 触发告警 + 记录历史 + 设置 last_triggered_at
条件仍满足 && 上次已触发 → 静默（不重复）
条件不再满足 && 上次已触发 → 恢复，清零 last_triggered_at（重新 arm）
```

一次跨越阈值只触发一次告警，恢复后才会重新 arm。

---

## 六、界面截图

### 6.1 资源看板 — 实时监控

![资源看板实时](screenshots/01-resource-dashboard-realtime.png)

展示多集群的 CPU / 内存 / NPU 使用率、执行中 Pod 列表，点击集群卡片可展开**节点级**资源详情。

### 6.2 告警规则 — 条件组表单

![告警规则创建](screenshots/03-alert-rule-create.png)

支持动态增删条件组和条件：

- **组间 AND**：所有组都必须满足才触发
- **组内可选 AND/OR**
- **排除按钮**：标记一个条件为 NOT
- 可选集群范围 + 节点范围

### 6.3 告警规则 — 列表

![告警规则列表](screenshots/04-alert-rules-list.png)

展示所有告警规则，条件以标签形式直观呈现，支持编辑、删除、查看历史。

### 6.4 节点级资源详情

![节点详情](screenshots/05-node-drawer.png)

每个集群展开后可见各节点的独立 CPU / 内存 / NPU 使用情况，告警规则可精确到具体节点。

### 6.5 邮件外发服务器 — 独立配置

![SMTP配置](screenshots/06-smtp-config.png)

SMTP 配置从每日报告页中提取为独立页面，作为**共享基础设施**供每日报告推送和告警规则通知共同使用。修改后立即生效，无需重启。

### 6.6 邮件服务器 — 连通性测试

![SMTP测试](screenshots/07-smtp-test-result.png)

配置完成后支持**一键测试连通性**：连接服务器 → STARTTLS（如需）→ 登录认证 → 发送测试邮件。逐步反馈每步结果，快速定位配置问题。

---

## 七、技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI (Python 3.11+) |
| ORM | SQLAlchemy 2.x (async) |
| 定时任务 | APScheduler (AsyncIOScheduler) |
| 指标采集 | kubernetes-asyncio |
| 邮件发送 | aiosmtplib |
| 前端 | React 18 + TypeScript + Ant Design 5 + React Query |

---

## 八、API 端点

### 告警规则

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/alert-rules` | 我的规则列表 |
| POST | `/api/v1/alert-rules` | 创建规则（含条件组） |
| PUT | `/api/v1/alert-rules/{id}` | 更新规则和条件 |
| DELETE | `/api/v1/alert-rules/{id}` | 删除规则 |
| GET | `/api/v1/alert-rules/{id}/history` | 规则触发历史 |
| GET | `/api/v1/alert-rules-history` | 全部触发历史 |

### SMTP 邮件服务器

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/system/config/smtp` | 获取 SMTP 配置 |
| PUT | `/api/v1/system/config/smtp` | 更新 SMTP 配置 |
| POST | `/api/v1/system/config/smtp/test` | 测试 SMTP 连通性 |
