# NPU 利用率趋势图功能设计

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在资源看板新增"趋势"页签，展示各集群（310P/A2/A3）的 NPU 利用率历史变化趋势，数据由 APScheduler 定时采集并存储在数据库，配置项可在系统管理页调整。

**Architecture:** APScheduler 定时任务按配置间隔（默认1分钟）调用现有 ResourceDashboardService 采集各集群 NPU 快照，存入 resource_npu_metrics 表；前端趋势页签通过 API 查询历史数据，按时间范围聚合展示 Recharts 折线图。

**Tech Stack:** SQLAlchemy ORM + APScheduler + Recharts LineChart + Ant Design Tabs

---

## 1. 数据采集层

### 新增 DB 表 `resource_npu_metrics`

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | Integer PK AUTO_INCREMENT | 自增 |
| `cluster_id` | Integer FK → kubernetes_cluster_configs.id | 集群 ID |
| `cluster_name` | String(100) | 集群名称（冗余便于查询） |
| `npu_total` | Float | 总 NPU 卡数 |
| `npu_used` | Float | 已用 NPU 卡数 |
| `npu_available` | Float | 可用 NPU 卡数 |
| `npu_utilization` | Float | 利用率 (used/total×100) |
| `collected_at` | TIMESTAMP | 采集时间戳 |

索引：`ix_resource_npu_metrics_cluster_collected` on `(cluster_id, collected_at)`

### DB 升级脚本

`backend/scripts/upgrade_v0.0.9.py`：创建 `resource_npu_metrics` 表及索引。

## 2. 定时采集任务

在 `scheduler.py` 新增 `_collect_resource_metrics_job`：
- 调用现有 `ResourceDashboardService` 逐集群获取实时 NPU 数据
- 存入 `resource_npu_metrics` 表
- 采集失败（集群不可达）时 log error 并 skip
- 间隔由 `ProjectDashboardConfig` 表 `resource_metrics_config` 的 `interval_minutes` 控制（默认 1）

## 3. 数据清理任务

在 `scheduler.py` 新增 `_cleanup_resource_metrics_job`：
- 每天 00:00 执行
- 删除超过保留天数的数据
- 保留天数由 `resource_metrics_config` 的 `retention_days` 控制（默认 30）

## 4. 配置管理

`ProjectDashboardConfig` 表新增 `config_key='resource_metrics_config'`：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `interval_minutes` | int | 1 | 数据采集间隔（分钟） |
| `retention_days` | int | 30 | 数据保留天数 |

配置通过前端「资源看板配置」页面修改。

## 5. 后端 API

新增端点：

| 端点 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/resource-dashboard/metrics/npu` | GET | 查询 NPU 趋势数据 | any user |
| `/resource-dashboard/metrics/config` | GET | 获取采集配置 | admin |
| `/resource-dashboard/metrics/config` | PUT | 更新采集配置 | super_admin |

`/metrics/npu` 参数：
- `cluster_ids[]`: 集群 ID 列表（可选，默认全部）
- `start_time`: ISO8601 起始时间（可选）
- `end_time`: ISO8601 结束时间（可选）
- `time_range`: 预设范围 `1h`/`24h`/`7d`/`30d`（默认 `24h`）

返回格式：
```json
{
  "clusters": [
    {
      "cluster_id": 1,
      "cluster_name": "A2 资源池",
      "metrics": [
        {"collected_at": "2026-06-08T08:00:00", "npu_utilization": 75.0, "npu_total": 16, "npu_used": 12, "npu_available": 4}
      ]
    }
  ]
}
```

前端根据时间范围自动聚合粒度：
- 近1小时：原始1分钟粒度
- 近24小时：聚合为5分钟粒度
- 近7天：聚合为1小时粒度
- 近30天：聚合为6小时粒度

聚合逻辑在后端 SQL 中实现（GROUP BY + AVG）。

## 6. 前端趋势页签

在 `ResourceDashboard.tsx` 新增 Ant Design `Tabs`：

- **Tab 1**: 实时看板（现有内容不变）
- **Tab 2**: NPU 趋势（新增）

趋势 Tab 内容：
- 时间范围选择：近1小时 / 近24小时 / 近7天 / 近30天（Radio.Group）
- 集群筛选（多选 Select）
- 每个集群一条 Recharts `LineChart` 折线
  - X 轴：时间
  - Y 轴：NPU 利用率（0-100%）
  - Tooltip 显示具体数值
- 空数据时展示 Empty 组件

## 7. 前端配置页

在 `ResourceDashboardConfig.tsx` 新增「数据采集配置」折叠面板：
- 采集间隔（分钟）：InputNumber，1-60
- 数据保留天数：InputNumber，1-365
- 保存按钮