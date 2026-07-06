# 机器维度 NPU 利用率趋势视图 — 设计方案

> vLLM Ascend Dashboard · 2026-07

---

## 一、背景与目标

### 1.1 现状

资源看板已具备：

- **实时看板**：多集群 CPU / 内存 / NPU 分配情况，集群卡片可展开节点级资源详情（Drawer）
- **NPU 趋势**：集群维度的 NPU 利用率历史趋势折线图，数据由 APScheduler 每分钟采集

采集层已存储**节点级指标**（`resource_node_metrics` 表），包含每台机器的 NPU / CPU / 内存利用率、执行中 Pod 数等时序数据，但**查询与展示层仅覆盖集群维度**，节点级数据仅用于实时快照，未提供历史趋势查询。

### 1.2 问题

- 无法查看**单台机器**的 NPU 利用率随时间变化趋势
- 无法横向对比多台机器的利用率，难以发现**负载失衡**（部分机器长期高负载、部分长期闲置）
- 无法定位**资源闲置**的具体机器（如某台 NPU 利用率长期为 0）

### 1.3 目标

- 在现有「NPU 趋势」Tab 的集群级图表下方，追加**机器维度** NPU 利用率趋势图表
- 按 A2 / A3 集群分组展示每台机器的利用率折线图和汇总表，直观对比负载分布
- 提供利用率汇总统计（均值 / 峰值 / 最低值），辅助判断负载均衡度、定位闲置/满载机器
- 复用已有采集数据，**无需新增采集任务或数据模型**

---

## 二、整体架构

```
┌────────────────┐    定时采集（每 1 分钟，已有）
│  K8s Cluster   │────────────────────────────┐
│  (Nodes/Pods)  │                            │
└────────────────┘                            ▼
                                    ┌──────────────────────┐
                                    │  Metric Storage       │
                                    │  resource_npu_metrics │  ← 集群级时序（已有）
                                    │  resource_node_       │  ← 节点级时序（已有，本次复用）
                                    │  metrics              │
                                    └──────┬───────────────┘
                                           │
                          ┌────────────────┼────────────────┐
                          ▼                                  ▼
                   ┌──────────────┐                  ┌──────────────┐
                   │ /metrics/npu │                  │ /metrics/    │  ← 新增
                   │ 集群维度查询  │                  │  nodes       │  节点维度查询
                   │   （已有）    │                  │              │
                   └──────┬───────┘                  └──────┬───────┘
                          │                                  │
                          └──────────────┬───────────────────┘
                                         ▼
                              ┌────────────────────┐
                              │  NPU 趋势 Tab       │  ← 已有 Tab，内部追加内容
                              │  ┌────────────────┐ │
                              │  │ 集群级折线图    │ │  已有
                              │  │ Pod/PR 趋势    │ │  已有
                              │  ├────────────────┤ │
                              │  │ 机器级折线图    │ │  ← 新增（按 A2/A3 分组，汇总表上方）
                              │  │ 机器利用率汇总表│ │  ← 新增（按 A2/A3 分组）
                              │  │  └ 行悬停弹出  │ │  ← Popover 迷你趋势图
                              │  │    迷你趋势图  │ │     （hover 时显示）
                              │  └────────────────┘ │
                              └────────────────────┘
```

**核心思路**：采集层和数据模型已就绪，本次仅需补齐后端查询 API + 在现有「NPU 趋势」Tab 内追加机器折线图 + 汇总表（行悬停弹出迷你趋势图）。不新增 Tab。

---

## 三、数据模型（无需变更）

### 3.1 现有表 `resource_node_metrics`

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | Integer PK | 自增 |
| `cluster_id` | Integer FK | 集群 ID |
| `cluster_name` | String(100) | 集群名称（冗余） |
| `node_name` | String(250) | 节点名称 |
| `cpu_cores_total` / `cpu_cores_used` / `cpu_cores_available` | Float | CPU 核数 |
| `cpu_utilization` | Float | CPU 利用率 (%) |
| `memory_bytes_total` / `memory_bytes_used` / `memory_bytes_available` | Float | 内存字节 |
| `memory_utilization` | Float | 内存利用率 (%) |
| `npu_total` / `npu_used` / `npu_available` | Float | NPU 卡数 |
| `npu_utilization` | Float | NPU 利用率 (%) |
| `executing_pods_count` | Integer | 执行中 Pod 数 |
| `collected_at` | TIMESTAMP | 采集时间戳 |

已有索引：`cluster_id`、`node_name`、`collected_at`。

> **结论**：表结构和采集逻辑均完备，本次方案不涉及任何 DDL 变更或迁移脚本。

---

## 四、后端设计

### 4.1 新增 Schema

文件：`backend/app/schemas/resource_metrics.py`

```python
class NodeMetricPoint(BaseModel):
    """单台机器单个时间点的指标"""
    collected_at: datetime
    npu_utilization: float = 0
    npu_total: float = 0
    npu_used: float = 0
    npu_available: float = 0
    cpu_utilization: float = 0
    memory_utilization: float = 0
    executing_pods_count: int = 0


class ClusterNodeMetrics(BaseModel):
    """单个集群下的机器指标集合"""
    cluster_id: int
    cluster_name: str
    nodes: list[NodeSeries] = Field(default_factory=list)


class NodeSeries(BaseModel):
    """单台机器的趋势序列"""
    node_name: str
    metrics: list[NodeMetricPoint] = Field(default_factory=list)


class NodeMetricsResponse(BaseModel):
    """机器维度指标查询响应"""
    clusters: list[ClusterNodeMetrics] = Field(default_factory=list)
```

在 `backend/app/schemas/__init__.py` 的 `__all__` 和 import 段中注册新 Schema。

### 4.2 新增查询方法

文件：`backend/app/services/resource_metrics.py`，`ResourceMetricsService` 类新增：

```python
async def query_node_metrics(
    self,
    cluster_ids: list[int] | None = None,
    node_names: list[str] | None = None,
    time_range: str = "24h",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict:
```

**逻辑说明**：

1. 复用 `TIME_RANGE_GRANULARITY` / `TIME_RANGE_DURATION` 进行时间范围与降采样粒度映射
2. 查询启用的集群（可按 `cluster_ids` 过滤）
3. 对每个集群，查询 `ResourceNodeMetrics` 表，按 `collected_at` 范围过滤，可选按 `node_names` 过滤
4. 按 `node_name` 分组，对每个 node 的时序数据执行与集群级相同的 `_time_bucket` 聚合
5. 聚合策略：NPU/CPU/内存利用率取均值，总量取末值，Pod 数取均值
6. 时区处理复用 `_normalize_metric` 的 UTC 补全逻辑

**聚合方法**（新增私有方法，与 `_aggregate_metrics` 平行）：

```python
def _aggregate_node_metrics(
    self, raw_metrics: list[ResourceNodeMetrics], granularity_minutes: int
) -> list[dict]:
    # 按 time_bucket 分组，对利用率取 AVG，对总量取 LAST
```

### 4.3 新增 API 端点

文件：`backend/app/api/v1/resource_metrics.py`

```python
@router.get("/metrics/nodes", response_model=NodeMetricsResponse)
async def get_node_metrics(
    db: DbSession,
    current_user: CurrentUser,
    cluster_ids: Annotated[list[int] | None, Query()] = None,
    node_names: Annotated[list[str] | None, Query()] = None,
    time_range: str = Query("24h", description="时间范围：1h/24h/7d/30d"),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
):
```

**API 规格**：

| 项目 | 内容 |
|------|------|
| 路径 | `GET /api/v1/resource-dashboard/metrics/nodes` |
| 权限 | 任意登录用户（与 `/metrics/npu` 一致） |
| 参数 | `cluster_ids[]`、`node_names[]`、`time_range`、`start_time`、`end_time` |
| 降采样 | 1h→原始 / 24h→5min / 7d→60min / 30d→360min（与集群级一致） |

**返回格式**：

```json
{
  "clusters": [
    {
      "cluster_id": 1,
      "cluster_name": "A2 资源池",
      "nodes": [
        {
          "node_name": "node-a2-01",
          "metrics": [
            {
              "collected_at": "2026-07-06T08:00:00+00:00",
              "npu_utilization": 75.0,
              "npu_total": 8,
              "npu_used": 6,
              "npu_available": 2,
              "cpu_utilization": 60.0,
              "memory_utilization": 55.0,
              "executing_pods_count": 3
            }
          ]
        }
      ]
    }
  ]
}
```

### 4.4 修复数据清理缺口

**问题**：现有 `cleanup_old_metrics()` 仅删除 `resource_npu_metrics`，未清理 `resource_node_metrics`，节点级数据会无限增长。

**修复**：在 `cleanup_old_metrics()` 中新增对 `ResourceNodeMetrics` 的删除：

```python
async def cleanup_old_metrics(self) -> int:
    config = await self._get_config()
    retention_days = config.get("retention_days", 30)
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    # 清理集群级
    stmt = delete(ResourceNpuMetrics).where(ResourceNpuMetrics.collected_at < cutoff)
    result = await self.db.execute(stmt)
    deleted = result.rowcount

    # 清理节点级（新增）
    node_stmt = delete(ResourceNodeMetrics).where(ResourceNodeMetrics.collected_at < cutoff)
    node_result = await self.db.execute(node_stmt)
    deleted += node_result.rowcount

    await self.db.commit()
    logger.info(f"Cleaned up {deleted} metrics records (cluster + node)")
    return deleted
```

---

## 五、前端设计

### 5.1 新增 Service 函数

文件：`frontend/src/services/resourceMetrics.ts`

```typescript
export interface NodeMetricPoint {
  collected_at: string
  npu_utilization: number
  npu_total: number
  npu_used: number
  npu_available: number
  cpu_utilization: number
  memory_utilization: number
  executing_pods_count: number
}

export interface NodeSeries {
  node_name: string
  metrics: NodeMetricPoint[]
}

export interface ClusterNodeMetrics {
  cluster_id: number
  cluster_name: string
  nodes: NodeSeries[]
}

export interface NodeMetricsResponse {
  clusters: ClusterNodeMetrics[]
}

export const getNodeMetrics = async (params: {
  cluster_ids?: number[]
  node_names?: string[]
  time_range?: string
}) => { /* 同 getNpuMetrics 模式 */ }
```

### 5.2 新增 Hook

文件：`frontend/src/hooks/useResourceMetrics.ts`

```typescript
export const useNodeMetrics = (params: {
  cluster_ids?: number[]
  node_names?: number[]
  time_range?: string
}) => {
  return useQuery({
    queryKey: ['node-metrics', params],
    queryFn: () => metricsApi.getNodeMetrics(params),
    refetchInterval: 60000,
    placeholderData: (prev) => prev,
  })
}
```

### 5.3 在现有 NpuTrendTab 内追加机器维度视图

文件：`frontend/src/pages/ResourceDashboard.tsx`

**不新增 Tab**，在现有「NPU 趋势」Tab（`NpuTrendTab` 组件）的集群级图表下方追加机器维度折线图 + 汇总表。Tabs 结构不变：

| Tab Key | 标签 | 组件 |
|---------|------|------|
| `realtime` | 实时看板 | `RealtimeDashboardTab`（已有，不变） |
| `trend` | NPU 趋势 | `NpuTrendTab`（已有，内部追加机器折线图 + 汇总表） |

#### 追加后的 NpuTrendTab 布局

```
┌─────────────────────────────────────────────────────────┐
│  [近1h] [近24h] [近7d] [近30d]   集群▾   机器▾          │  筛选栏（机器▾为新增）
├─────────────────────────────────────────────────────────┤
│                                                         │
│  NPU 利用率趋势（集群维度）                       已有   │
│  ┌─────────────────────────────────────────────┐        │
│  │  A2 资源池 ━━ 75%    A3 资源池 ━━ 40%       │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Pod / PR 数量趋势                                已有   │
│  ┌─────────────────────────────────────────────┐        │
│  │  A2 Pod数 ━━    A3 Pod数 ━━                 │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
├═════════════════════════════════════════════════════════┤  以下新增
│                                                         │
│  A2 资源池 — 机器 NPU 利用率趋势                 新增   │
│  ┌─────────────────────────────────────────────┐        │
│  │  node-a2-01 ━━ 75%                          │        │
│  │  node-a2-02 ━━ 30%                          │        │
│  │  node-a2-03 ━━ 0%  (闲置)                   │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  A3 资源池 — 机器 NPU 利用率趋势                 新增   │
│  ┌─────────────────────────────────────────────┐        │
│  │  node-a3-01 ━━ 60%                          │        │
│  │  node-a3-02 ━━ 90%  (满载)                  │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  机器利用率汇总（按集群分组）                     新增   │
│  ┌──────────┬──────┬──────┬──────┬──────┬──────┬──────┐│
│  │ 集群     │ 机器 │ 均值 │ 峰值 │ 最低 │NPU卡 │ 状态 ││
│  │ A2 资源池│a2-01 │ 72%  │ 100% │ 25%  │ 8    │ 满载 ││
│  │ A2 资源池│a2-02 │ 30%  │ 60%  │ 0%   │ 8    │      ││
│  │ A2 资源池│a2-03 │ 0%   │ 0%   │ 0%   │ 8    │ 闲置 ││
│  │A2 汇总   │3台   │34.0% │  —   │  —   │ 24   │极差72%││
│  │          │      │      │      │      │      │负载失衡│
│  │ A3 资源池│a3-01 │ 60%  │ 80%  │ 20%  │ 8    │      ││
│  │ A3 资源池│a3-02 │ 90%  │ 100% │ 50%  │ 8    │ 满载 ││
│  │A3 汇总   │2台   │75.0% │  —   │  —   │ 16   │极差30%││
│  │          │      │      │      │      │      │轻度不均│
│  └──────────┴──────┴──────┴──────┴──────┴──────┴──────┘│
│                                                         │
│  鼠标悬停任一机器行时弹出 Popover：                      │
│  ┌─────────────────────────────────────┐                │
│  │  node-a2-01                         │                │
│  │  ┌─────────────────────────────┐    │  迷你 NPU      │
│  │  │     ╱╲    ╱╲                 │    │  利用率趋势图  │
│  │  │  ╱╲╱  ╲╱╲╱  ╲╲              │    │  (Sparkline)   │
│  │  │                ╲╲            │    │                │
│  │  └─────────────────────────────┘    │                │
│  │  0%──────────────────────100%       │                │
│  └─────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────┘
```

**设计要点**：

- **折线图区（汇总表上方）**：按 A2 / A3 集群分组，每个集群一张独立 Card，始终可见，展示该集群下所有机器的 NPU 利用率折线；每张图附带**集群均值参考线**（黄色虚线），高于/低于参考线的机器一目了然，直观反映负载失衡
- **汇总表（折线图下方）**：按集群分组的统计表，含均值/峰值/最低值/状态标记；**表尾追加集群汇总行**，展示集群整体均值、机器数、NPU 总卡数，并通过**极差**（集群内最高机器均值 − 最低机器均值）量化均衡度，自动标记"负载均衡/轻度不均/负载失衡"
- **行悬停 Popover**：鼠标悬停汇总表机器行时，`Popover` 弹出该机器的迷你 NPU 利用率趋势图（Sparkline），内容仅含趋势图本身，不附加额外数值

#### 实现方式

在 `NpuTrendTab` 组件中新增 `useNodeMetrics` 调用，复用同一组 `timeRange` / `selectedClusters` 状态，追加一个机器筛选 Select、按集群分组的机器折线图、机器利用率汇总表：

**1. 筛选栏扩展**

在现有筛选栏 Card 中追加机器多选 Select，选项随集群筛选联动：

```tsx
// NpuTrendTab 内已有 selectedClusters、timeRange 状态
const [selectedNodes, setSelectedNodes] = useState<string[]>([])

const { data: nodeMetricsData } = useNodeMetrics({
  cluster_ids: activeClusterIds.length > 0 ? activeClusterIds : undefined,
  time_range: timeRange,
})
```

**2. 按集群分组的机器折线图（汇总表上方，始终可见）**

为每个集群（A2 / A3）渲染一张独立的折线图 Card，标题为 `{集群名} — 机器 NPU 利用率趋势`，展示该集群下所有（或选中）机器的 NPU 利用率折线：

```tsx
{nodeMetricsData?.clusters?.map(cluster => {
  const visibleNodes = selectedNodes.length
    ? cluster.nodes.filter(n => selectedNodes.includes(n.node_name))
    : cluster.nodes
  if (visibleNodes.length === 0) return null

  // 为该集群的机器组装 chartData（同集群趋势的拍平逻辑）
  const chartData = buildNodeChartData(visibleNodes, timeRange)

  // 计算该集群所有机器的整体平均利用率，作为参考线
  const clusterAvg = visibleNodes.length > 0
    ? visibleNodes.reduce((sum, n) =>
        sum + n.metrics.reduce((s, m) => s + m.npu_utilization, 0) / (n.metrics.length || 1), 0
      ) / visibleNodes.length
    : 0

  return (
    <Card key={cluster.cluster_id} title={`${cluster.cluster_name} — 机器 NPU 利用率趋势`}>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="timeLabel" tick={{ fontSize: 12 }} angle={-30} textAnchor="end" height={50} />
          <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip content={<NodeTrendTooltipContent />} />
          <Legend />
          <ReferenceLine
            y={clusterAvg}
            stroke="#faad14"
            strokeDasharray="6 4"
            label={{ value: `集群均值 ${clusterAvg.toFixed(1)}%`, position: 'right', fontSize: 11, fill: '#faad14' }}
          />
          {visibleNodes.map((node, i) => (
            <Line
              key={node.node_name}
              type="monotone"
              dataKey={`npu_${node.node_name}`}
              name={node.node_name}
              stroke={NODE_COLORS[i % NODE_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 2 }}
              connectNulls
              unit="%"
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </Card>
  )
})}
```

折线图 Tooltip（`NodeTrendTooltipContent`）hover 单个时间点时展示该机器的 NPU 利用率、CPU 利用率、执行中 Pod 数：

```tsx
function NodeTrendTooltipContent({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#fff', border: '1px solid #eee', padding: 12, borderRadius: 4, maxWidth: 400 }}>
      <Text strong>{dayjs(label).format('YYYY-MM-DD HH:mm')}</Text>
      {payload.map((p: any) => {
        const nodeName = p.dataKey.replace('npu_', '')
        const cpuVal = p.payload?.[`cpu_${nodeName}`]
        const podsVal = p.payload?.[`pods_${nodeName}`]
        return (
          <div key={nodeName} style={{ marginTop: 4 }}>
            <Text strong style={{ fontSize: 13 }}>{nodeName}</Text>
            <div style={{ fontSize: 12, color: p.color }}>
              NPU: {p.value.toFixed(1)}%
              {cpuVal != null && ` · CPU: ${cpuVal.toFixed(1)}%`}
              {podsVal != null && ` · Pod: ${podsVal}`}
            </div>
          </div>
        )
      })}
    </div>
  )
}
```

**3. 机器利用率汇总表（折线图下方，始终可见）**

单张 Table，含「集群」列实现 A2 / A3 分组，按集群 + 机器名排序。每行通过 `Popover` 包裹，悬停时弹出迷你趋势图。**表尾增加每个集群的汇总行，量化负载均衡度**：

```tsx
const summaryRows = useMemo(() => {
  const rows: NodeSummaryRow[] = []
  for (const cluster of nodeMetricsData?.clusters || []) {
    for (const node of cluster.nodes) {
      if (selectedNodes.length && !selectedNodes.includes(node.node_name)) continue
      const utils = node.metrics.map(m => m.npu_utilization)
      if (utils.length === 0) continue
      rows.push({
        key: `${cluster.cluster_id}-${node.node_name}`,
        cluster_id: cluster.cluster_id,
        cluster_name: cluster.cluster_name,
        node_name: node.node_name,
        avg: utils.reduce((s, v) => s + v, 0) / utils.length,
        max: Math.max(...utils),
        min: Math.min(...utils),
        npu_total: node.metrics[node.metrics.length - 1]?.npu_total ?? 0,
        metrics: node.metrics, // 保留原始时序数据，供 Popover 迷你图使用
      })
    }
  }
  return rows.sort((a, b) =>
    a.cluster_name.localeCompare(b.cluster_name) || a.node_name.localeCompare(b.node_name))
}, [nodeMetricsData, selectedNodes])
```

表格列定义：

| 列 | dataIndex | 说明 |
|----|-----------|------|
| 集群 | `cluster_name` | A2 资源池 / A3 资源池，支持筛选 |
| 机器 | `node_name` | 节点名 |
| 均值 | `avg` | 选定时间范围内 NPU 利用率均值，格式 `xx.x%` |
| 峰值 | `max` | 最大值 |
| 最低 | `min` | 最小值 |
| NPU 卡数 | `npu_total` | 末值快照 |
| 状态 | — | 均值 < 5% → `Tag color="orange"` "疑似闲置"；峰值 = 100% → `Tag color="red"` "存在满载" |

**集群汇总行（Table `summary`）**：

利用 Ant Design Table 的 `summary` 渲染器，在每个集群的机器行末尾追加一行集群级统计，量化该集群内各机器的负载均衡度：

```tsx
// 按集群分组计算机器级统计
const clusterSummaries = useMemo(() => {
  const map = new Map<number, {
    cluster_id: number
    cluster_name: string
    nodeAvgs: number[]   // 各机器的利用率均值
    nodeCount: number
    npuTotal: number
  }>()
  for (const row of summaryRows) {
    if (!map.has(row.cluster_id)) {
      map.set(row.cluster_id, {
        cluster_id: row.cluster_id,
        cluster_name: row.cluster_name,
        nodeAvgs: [],
        nodeCount: 0,
        npuTotal: 0,
      })
    }
    const entry = map.get(row.cluster_id)!
    entry.nodeAvgs.push(row.avg)
    entry.nodeCount += 1
    entry.npuTotal += row.npu_total
  }

  const result: ClusterSummary[] = []
  for (const entry of map.values()) {
    const avgOfAvgs = entry.nodeAvgs.reduce((s, v) => s + v, 0) / entry.nodeAvgs.length
    const maxOfAvgs = Math.max(...entry.nodeAvgs)
    const minOfAvgs = Math.min(...entry.nodeAvgs)
    const spread = maxOfAvgs - minOfAvgs                    // 极差：最高与最低机器均值之差
    const variance = entry.nodeAvgs.reduce((s, v) => s + (v - avgOfAvgs) ** 2, 0) / entry.nodeAvgs.length
    const stdDev = Math.sqrt(variance)                      // 标准差：衡量离散程度
    result.push({
      ...entry,
      cluster_avg: avgOfAvgs,
      cluster_spread: spread,
      cluster_stddev: stdDev,
    })
  }
  return result
}, [summaryRows])
```

汇总行渲染：

```tsx
<Table
  dataSource={summaryRows}
  ...
  summary={() => (
    <>
      {clusterSummaries.map(cs => (
        <Table.Summary.Row key={cs.cluster_id} style={{ background: '#fafafa', fontWeight: 600 }}>
          <Table.Summary.Cell index={0}>{cs.cluster_name} 汇总</Table.Summary.Cell>
          <Table.Summary.Cell index={1}>{cs.nodeCount} 台</Table.Summary.Cell>
          <Table.Summary.Cell index={2}>{cs.cluster_avg.toFixed(1)}%</Table.Summary.Cell>
          <Table.Summary.Cell index={3}>—</Table.Summary.Cell>
          <Table.Summary.Cell index={4}>—</Table.Summary.Cell>
          <Table.Summary.Cell index={5}>{cs.npuTotal}</Table.Summary.Cell>
          <Table.Summary.Cell index={6}>
            <Space size={4}>
              <span>极差 {cs.cluster_spread.toFixed(1)}%</span>
              {cs.cluster_spread >= 50
                ? <Tag color="red">负载失衡</Tag>
                : cs.cluster_spread >= 30
                  ? <Tag color="orange">轻度不均</Tag>
                  : <Tag color="green">负载均衡</Tag>}
            </Space>
          </Table.Summary.Cell>
        </Table.Summary.Row>
      ))}
    </>
  )}
/>
```

**均衡度判定规则**：

| 极差（集群内最高机器均值 − 最低机器均值） | 判定 | 标签颜色 |
|------------------------------------------|------|----------|
| ≥ 50% | 负载失衡 | 红色 |
| 30% ~ 50% | 轻度不均 | 橙色 |
| < 30% | 负载均衡 | 绿色 |

> 极差直观反映集群内"最忙"与"最闲"机器的利用率差距，是负载失衡最易理解的量化指标。标准差（`cluster_stddev`）作为辅助参考，数据保留但不直接展示，供后续演进使用。

**4. 行悬停 Popover — 迷你 NPU 利用率趋势图**

每行机器名单元格用 `Popover` 包裹，`trigger="hover"`，`placement="right"`。Popover 内容仅渲染一张无坐标轴的迷你折线图（Sparkline）：

```tsx
function NodeSparkline({ metrics, timeRange }: {
  metrics: NodeMetricPoint[]
  timeRange: string
}) {
  const data = metrics.map(m => ({
    timeLabel: dayjs(m.collected_at).format(timeRange === '1h' ? 'HH:mm' : 'MM-DD'),
    npu: m.npu_utilization,
  }))
  return (
    <ResponsiveContainer width={280} height={120}>
      <LineChart data={data}>
        <Line
          type="monotone"
          dataKey="npu"
          stroke="#1677ff"
          strokeWidth={2}
          dot={false}
          connectNulls
          unit="%"
        />
        <YAxis domain={[0, 100]} hide />
        <Tooltip
          formatter={(v: number) => [`${v.toFixed(1)}%`, 'NPU 利用率']}
          labelStyle={{ fontSize: 12 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
```

表格「机器」列的渲染：

```tsx
{
  title: '机器',
  dataIndex: 'node_name',
  width: 220,
  render: (nodeName: string, record: NodeSummaryRow) => (
    <Popover
      trigger="hover"
      placement="right"
      mouseEnterDelay={0.3}
      title={nodeName}
      content={<NodeSparkline metrics={record.metrics} timeRange={timeRange} />}
    >
      <span style={{ cursor: 'pointer' }}>{nodeName}</span>
    </Popover>
  ),
}
```

**Popover 内容说明**：

| 元素 | 内容 |
|------|------|
| 标题 | 机器名（`node_name`） |
| 主体 | 迷你 NPU 利用率折线图（280×120px），无 X/Y 坐标轴，仅一条蓝色折线 |
| 图内 Tooltip | hover 折线上的点时显示「NPU 利用率: xx.x%」+ 时间 |

> 汇总表已展示均值/峰值/最低值/NPU卡数/状态，Popover 不重复这些数值，仅提供直观的趋势形态。

**5. 机器选项联动**

```typescript
const nodeOptions = useMemo(() => {
  const seen = new Map<string, { label: string; value: string }>()
  for (const cluster of nodeMetricsData?.clusters || []) {
    if (selectedClusters.length && !selectedClusters.includes(cluster.cluster_id)) continue
    for (const node of cluster.nodes) {
      if (!seen.has(node.node_name)) {
        seen.set(node.node_name, {
          label: `${node.node_name} (${cluster.cluster_name})`,
          value: node.node_name,
        })
      }
    }
  }
  return Array.from(seen.values())
}, [nodeMetricsData, selectedClusters])
```

**6. 空数据处理**

集群级已有数据但节点级无数据时（如采集任务未写入 `resource_node_metrics`），汇总表区域展示 `<Empty description="暂无机器级趋势数据" />`。

---

## 六、变更清单

### 后端

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `backend/app/schemas/resource_metrics.py` | 新增 | `NodeMetricPoint`、`NodeSeries`、`ClusterNodeMetrics`、`NodeMetricsResponse` |
| `backend/app/schemas/__init__.py` | 修改 | 注册新 Schema 到 `__all__` 和 import 段 |
| `backend/app/services/resource_metrics.py` | 修改 | 新增 `query_node_metrics()`、`_aggregate_node_metrics()`；修复 `cleanup_old_metrics()` 补充节点级清理 |
| `backend/app/api/v1/resource_metrics.py` | 修改 | 新增 `GET /metrics/nodes` 端点 |

### 前端

| 文件 | 变更类型 | 内容 |
|------|----------|------|
| `frontend/src/services/resourceMetrics.ts` | 修改 | 新增 `NodeMetricPoint`、`NodeSeries`、`ClusterNodeMetrics`、`NodeMetricsResponse` 类型 + `getNodeMetrics()` 函数 |
| `frontend/src/hooks/useResourceMetrics.ts` | 修改 | 新增 `useNodeMetrics` hook |
| `frontend/src/pages/ResourceDashboard.tsx` | 修改 | 在 `NpuTrendTab` 内追加机器筛选 Select、按集群分组的机器折线图（汇总表上方）、机器利用率汇总表（行悬停 Popover 迷你趋势图）；新增 `NodeTrendTooltipContent`、`NodeSparkline` 组件。**不新增 Tab** |

### 不涉及变更

- 数据库表结构 / 迁移脚本（`resource_node_metrics` 已存在）
- 采集任务（`collect_snapshot` 已写入节点级数据）
- 定时调度（`scheduler.py` 无需改动，清理任务复用现有 `_cleanup_resource_metrics_job`）

---

## 七、测试方案

### 7.1 后端单元测试

文件：`backend/tests/test_resource_metrics.py`（扩展）

| 测试用例 | 验证点 |
|----------|--------|
| `test_query_node_metrics_basic` | 返回结构正确，clusters → nodes → metrics 嵌套层级正确 |
| `test_query_node_metrics_filter_cluster` | `cluster_ids` 过滤生效 |
| `test_query_node_metrics_filter_node_names` | `node_names` 过滤生效 |
| `test_query_node_metrics_time_range` | 不同 `time_range` 降采样粒度正确（1h 原始 / 24h 5min / 7d 60min） |
| `test_query_node_metrics_aggregation` | 聚合后利用率取均值、总量取末值 |
| `test_query_node_metrics_empty` | 无数据时返回空数组 |
| `test_cleanup_old_metrics_node` | 清理任务同时删除集群级和节点级过期数据 |

### 7.2 前端验证

| 验证点 | 方法 |
|--------|------|
| 机器折线图 + 汇总表在 NPU 趋势 Tab 内渲染 | 切换到「NPU 趋势」Tab，集群级图表下方可见按集群分组的机器折线图，再下方为汇总表 |
| A2 / A3 分组展示 | 每个集群一张独立折线图 Card，汇总表「集群」列区分 A2 / A3，支持按集群筛选 |
| 折线图 Tooltip | hover 折线上的点显示各机器 NPU 利用率 + CPU 利用率 + Pod 数 |
| 行悬停弹出迷你趋势图 | 鼠标悬停汇总表机器名，0.3s 后右侧弹出 Popover，含 280×120 迷你 NPU 利用率折线图 |
| Popover 内容仅趋势图 | Popover 内只有折线图 + 机器名标题，不含额外数值 |
| 迷你图内 Tooltip | hover 迷你折线上的点显示「NPU 利用率: xx.x%」+ 时间 |
| 时间范围切换 | 切换 1h/24h/7d/30d，折线图、汇总表、迷你趋势图同步更新 |
| 集群筛选联动 | 选择集群后，折线图仅显示对应集群，机器 Select 选项收窄，汇总表同步 |
| 机器多选筛选 | 选择特定机器后，折线图和汇总表仅显示选中机器 |
| 汇总表统计值 | 均值/峰值/最低值与折线图数据一致 |
| 集群均值参考线 | 折线图中黄色虚线标注集群平均利用率，标签显示"集群均值 xx.x%" |
| 集群汇总行 | 每个集群机器行末尾有汇总行，显示机器数、集群均值、NPU 总卡数、极差 |
| 均衡度标签 | 极差 ≥ 50% 标"负载失衡"(红)，30~50% 标"轻度不均"(橙)，< 30% 标"负载均衡"(绿) |
| 闲置/满载标记 | 均值 < 5% 标"疑似闲置"，峰值 = 100% 标"存在满载" |
| 空数据 | 集群级有数据但节点级无数据时，折线图和汇总表区域展示 Empty 组件 |

### 7.3 验证命令

```bash
# 后端
cd backend
uv run pytest tests/test_resource_metrics.py -v
uv run ruff check app/services/resource_metrics.py app/api/v1/resource_metrics.py app/schemas/resource_metrics.py
uv run mypy app/services/resource_metrics.py app/api/v1/resource_metrics.py

# 前端
cd frontend
pnpm lint
pnpm build
```

---

## 八、性能考量

| 场景 | 数据量估算 | 应对措施 |
|------|------------|----------|
| 30 天 / 1 分钟粒度 / 20 台机器 | 20 × 43200 = 86 万行 | 降采样至 6 小时粒度 → 20 × 120 = 2400 点 |
| 7 天 / 1 分钟粒度 / 20 台机器 | 20 × 10080 = 20 万行 | 降采样至 1 小时粒度 → 20 × 168 = 3360 点 |
| 24 小时 / 1 分钟粒度 / 20 台机器 | 20 × 1440 = 2.9 万行 | 降采样至 5 分钟粒度 → 20 × 288 = 5760 点 |

- 查询走 `(cluster_id, collected_at)` 和 `node_name` 索引，单次查询 < 200ms
- 前端折线图按集群分组渲染，单 Card 内机器数通常 ≤ 10，渲染压力可控
- 机器数 > 15 时可通过机器 Select 按需筛选，避免单图折线过多
- 汇总表统计值在 `useMemo` 中计算，仅依赖 `nodeMetricsData` 和 `selectedNodes`
- Popover 迷你图仅悬停时按需渲染单个实例，不增加常驻渲染开销
- `refetchInterval` 60 秒，与集群趋势一致

---

## 九、后续演进方向（本次不做）

1. **CPU / 内存利用率趋势**：`NodeMetricPoint` 已包含 `cpu_utilization` / `memory_utilization`，后续可在折线图和 Popover 迷你图中增加多指标切换
2. **均衡度评分增强**：本次以极差量化均衡度，后续可引入标准差/变异系数综合评分，并支持历史趋势对比
3. **异常检测**：机器利用率突降/突升自动标注，辅助定位突发问题
4. **与告警规则联动**：在汇总表中为每台机器提供"创建告警规则"快捷入口
