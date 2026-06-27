# 日志中心设计文档

**日期**: 2026-06-26
**版本**: v1.0
**状态**: 待实现

---

## 1. 概述

### 1.1 背景

项目已收集了各类日志（Claude Code CLI 调用日志、Failure Analysis 报告、应用日志），但前端缺少统一的日志查看入口。当前各日志源散落各处，调试和排查问题时需要到不同地方查看，效率低下。

### 1.2 目标

构建统一的日志中心，以 Datadog/Grafana 风格展示项目内产生的所有日志，支持按来源/级别过滤、全文搜索、时间范围筛选、分页查看。

### 1.3 日志源

| 日志源 | source key | 存储位置 | 格式 |
|--------|-----------|---------|------|
| Claude Code CLI 调用日志 | `claude_cli` | `data/claude_logs/` 文件系统 | 结构化纯文本 |
| Failure Analysis 报告 | `failure_analysis` | `data/failure-analysis/` 文件系统 | Markdown |
| 后端应用日志 | `app` | MySQL `app_logs` 表（新增） | 结构化 |
| 调度器日志 | `scheduler` | MySQL `app_logs` 表（复用） | 结构化 |

---

## 2. 架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                   Frontend                           │
│  LogCenter Page (Datadog 风格左右布局)                │
│  ┌──────────┐  ┌────────────────────────────────┐   │
│  │ Source   │  │  Log Stream (Virtual Scroller)  │   │
│  │ Filter   │  │  • 搜索栏 + 时间选择器           │   │
│  │          │  │  • 带级别/来源标签的日志条目      │   │
│  │ • 日志源 │  │  • 点击展开完整内容 (monospace)  │   │
│  │ • 级别   │  │  • 复制、跳转源链接              │   │
│  │ • 时间   │  │  • 底部分页器                    │   │
│  │ • 统计   │  │                                  │   │
│  └──────────┘  └────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────┘
                       │ POST /api/v1/logs/query
                       │ GET  /api/v1/logs/sources
                       │ GET  /api/v1/logs/{id}
┌──────────────────────▼──────────────────────────────┐
│                   Backend                            │
│  app/api/v1/logs.py         路由层                    │
│  app/schemas/logs.py        请求/响应 schema          │
│  app/services/log_service.py 业务逻辑层               │
│    • 多源并发查询                                      │
│    • 结果合并/排序/分页                                 │
│    • 全文搜索 (MySQL FULLTEXT + LIKE 兜底)            │
│  app/core/logging.py        DB 日志 handler           │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  Log Sources                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ CLI Logs │ │ Analysis │ │ App Logs │             │
│  │ (file)   │ │ Reports  │ │ (MySQL)  │             │
│  │          │ │ (file)   │ │          │             │
│  └──────────┘ └──────────┘ └──────────┘             │
└─────────────────────────────────────────────────────┘
```

### 2.2 统一日志 Schema

```python
class UnifiedLogEntry:
    id: str              # "claude_cli:2026-06-26:143000_anthropic_claude-sonnet"
    source: str          # "claude_cli" | "failure_analysis" | "app" | "scheduler"
    level: str           # "debug" | "info" | "warning" | "error"
    timestamp: datetime  # ISO 8601
    summary: str         # 单行摘要（列表展示用），≤200 字符
    content: str         # 完整日志内容（detail 接口返回全文，列表接口可截断）
    metadata: dict       # 来源相关元数据，见下方定义
```

**metadata 按 source 区分**:

| source | metadata 字段 |
|--------|-------------|
| `claude_cli` | `provider`, `model`, `duration_seconds`, `exit_code`, `route` |
| `failure_analysis` | `workflow_name`, `job_name`, `job_id`, `analysis_status` |
| `app` | `module`, `function_name`, `line_number` |
| `scheduler` | `task_name`, `status` |

---

## 3. 数据库设计

### 3.1 新增表：`app_logs`

```sql
CREATE TABLE app_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME(3) NOT NULL COMMENT '日志产生时间',
    level VARCHAR(10) NOT NULL COMMENT 'DEBUG/INFO/WARNING/ERROR',
    module VARCHAR(200) COMMENT '日志来源模块',
    function_name VARCHAR(200) COMMENT '函数名',
    line_number INT COMMENT '行号',
    message TEXT NOT NULL COMMENT '日志正文',
    traceback TEXT COMMENT '异常堆栈',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_timestamp (timestamp),
    INDEX idx_level (level),
    INDEX idx_module (module),
    FULLTEXT INDEX ft_message (message) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

> **MySQL 版本要求**: FULLTEXT WITH PARSER ngram 需要 MySQL 5.7.6+。若版本不满足，降级为普通 INDEX + LIKE 查询，建表时跳过 FULLTEXT 行。

### 3.2 DB Log Handler

新增 `backend/app/core/logging.py`，实现自定义 `logging.Handler`：

- 在 `emit()` 中异步写入 `app_logs` 表
- 使用队列缓冲（`QueueHandler` + `QueueListener`）避免阻塞主线程
- 在 `main.py` 的 `create_app()` 中注册
- 保留现有 stdout 输出不变

---

## 4. 后端 API 设计

### 4.1 路由注册

在 `main.py` 中新增：
```python
app.include_router(logs.router, prefix="/api/v1/logs", tags=["日志中心"])
```

### 4.2 API 清单

#### `GET /api/v1/logs/sources`

获取可用日志源列表及统计。

**响应**:
```json
{
  "sources": [
    {"key": "claude_cli", "label": "Claude CLI", "count": 234, "last_entry": "2026-06-26T14:30:00Z"},
    {"key": "failure_analysis", "label": "失败分析", "count": 56, "last_entry": "2026-06-26T12:00:00Z"},
    {"key": "app", "label": "应用日志", "count": 890, "last_entry": "2026-06-26T14:35:00Z"},
    {"key": "scheduler", "label": "调度器", "count": 120, "last_entry": "2026-06-26T14:00:00Z"}
  ]
}
```

#### `POST /api/v1/logs/query`

统一日志查询。

**请求体**:
```json
{
  "sources": ["claude_cli", "app"],
  "levels": ["error", "warning"],
  "time_range": {
    "start": "2026-06-25T00:00:00Z",
    "end": "2026-06-26T23:59:59Z"
  },
  "search": "timeout",
  "page": 1,
  "page_size": 50
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sources` | string[] | 否 | 日志源过滤，空=全部 |
| `levels` | string[] | 否 | 级别过滤 |
| `time_range.start` | string | 否 | 开始时间 ISO 8601 |
| `time_range.end` | string | 否 | 结束时间 ISO 8601 |
| `search` | string | 否 | 全文搜索关键词 |
| `page` | int | 是 | 页码，从 1 开始 |
| `page_size` | int | 是 | 每页条数，默认 50，最大 200 |

**响应**:
```json
{
  "total": 1234,
  "page": 1,
  "page_size": 50,
  "entries": [
    {
      "id": "claude_cli:2026-06-26:143000_anthropic_claude-sonnet-4-20250514",
      "source": "claude_cli",
      "level": "error",
      "timestamp": "2026-06-26T14:30:00Z",
      "summary": "CLI 调用异常: timeout after 180s, exit_code=1...",
      "content": "...(截断或完整，视接口而定)...",
      "metadata": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "duration_seconds": 180.5,
        "exit_code": 1,
        "route": "direct"
      }
    }
  ]
}
```

#### `GET /api/v1/logs/{log_id}`

获取单条日志完整内容。`log_id` 格式: `{source}:{date}:{identifier}`，需 URL encode。

### 4.3 LogService 实现要点

`backend/app/services/log_service.py`:

```
query(filters) →
  1. 解析 filters.sources → 确定查询哪些源
  2. 对所有目标源并发查询:
     - claude_cli:    扫描 data/claude_logs/{date}/ 目录，解析 .log 文件
     - failure_analysis: 扫描 data/failure-analysis/ 目录 + DB 元数据
     - app/scheduler: 查询 MySQL app_logs 表
  3. 各源返回 UnifiedLogEntry 列表
  4. 合并 → 按 timestamp 倒序排序
  5. 应用 search 过滤（MySQL 走 SQL 层过滤，文件源走 Python 内存过滤）
  6. 分页 → 返回
```

**关键细节**:
- 搜索策略分层：app_logs 用 `MATCH AGAINST`（优先）或 `LIKE` 兜底；文件源用 Python 内存匹配
- 时间范围：各源在查询阶段就应用时间过滤，减少内存开销
- 文件源缓存：CLI 日志目录结构按日期分层，利用目录名跳过不需要的日期

---

## 5. 前端设计

### 5.1 新增/修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/pages/LogCenter.tsx` | 新增 | 日志中心主页面 |
| `frontend/src/pages/LogCenter.css` | 新增 | 页面样式 |
| `frontend/src/services/logs.ts` | 新增 | 日志 API 客户端 |
| `frontend/src/hooks/useLogs.ts` | 新增 | React Query hooks |
| `frontend/src/components/LogEntry.tsx` | 新增 | 单条日志条目组件 |
| `frontend/src/App.tsx` | 修改 | 添加 `/logs` 路由 |
| `frontend/src/components/Layout.tsx` | 修改 | 侧边栏添加"日志中心"菜单 |

### 5.2 页面布局

Datadog 风格左右布局：
- **左侧过滤面板 (280px)**：日志源勾选、级别勾选、时间快捷选项、各源统计数
- **右侧主区域**：顶部搜索栏+时间选择器 → 日志条目列表（虚拟滚动）→ 底部分页器

### 5.3 核心交互

| 交互 | 行为 |
|------|------|
| **过滤变更** | 任一过滤条件变化 → 重置到第 1 页 → 重新请求 |
| **搜索** | 输入关键词 → 防抖 300ms → 自动搜索 |
| **时间快捷** | 预设：最近 1h / 24h / 7d / 自定义（DatePicker） |
| **展开/折叠** | 点击日志条目 → 展开完整内容（`<pre>` + monospace） |
| **级别着色** | ERROR=红色、WARNING=橙色、INFO=蓝色、DEBUG=灰色 |
| **复制** | hover 显示复制按钮 → 复制完整日志内容 |
| **虚拟滚动** | 使用 antd Table `virtual` 模式，支持万级数据 |
| **分页** | 后端分页，底部分页器显示总数 |

### 5.4 组件树

```
LogCenter
├── LogFilterSidebar
│   ├── Checkbox.Group (日志源)
│   ├── Checkbox.Group (级别)
│   ├── Radio.Group (时间快捷)
│   ├── RangePicker (自定义时间)
│   └── SourceStats (各源计数)
└── LogMainArea
    ├── LogToolbar
    │   ├── Search Input
    │   └── Time Range Display
    ├── LogList (Table, virtual)
    │   └── LogEntry[] (可展开行)
    │       ├── Timestamp (formatted)
    │       ├── LevelTag (colored)
    │       ├── SourceTag
    │       ├── Summary (truncated)
    │       └── ExpandedContent
    │           ├── <pre> full log content
    │           ├── Metadata tags
    │           └── Copy button
    └── Pagination
```

### 5.5 样式

- 左侧面板：深色背景（与现有 Stripe Sider 一致）
- 日志列表：白底 + 浅灰分割线
- 日志条目 hover：浅蓝背景
- 展开区域：浅灰背景 + `font-family: 'Consolas', 'Monaco', monospace`
- 级别色：ERROR `#ff4d4f`、WARNING `#fa8c16`、INFO `#1890ff`、DEBUG `#8c8c8c`

### 5.6 路由与导航

- 路由: `/logs` → `LogCenter`（需登录，ProtectedRoute）
- 侧边栏菜单位置: 放在 "测试看板" 下方，使用 `FileSearchOutlined` 或 `ReadOutlined` 图标

---

## 6. 实现计划概要

### 阶段 1：后端基础设施
1. 新建 `app_logs` 表（数据库迁移脚本）
2. 新建 `app/core/logging.py` DB Log Handler
3. 在 `main.py` 注册 DB Log Handler

### 阶段 2：后端 API
4. 新建 `app/schemas/logs.py` 请求/响应 schema
5. 新建 `app/services/log_service.py` 日志查询服务
6. 新建 `app/api/v1/logs.py` API 路由
7. 在 `main.py` 注册路由

### 阶段 3：前端
8. 新建 `frontend/src/services/logs.ts` API 层
9. 新建 `frontend/src/hooks/useLogs.ts` Hooks
10. 新建 `frontend/src/components/LogEntry.tsx` 组件
11. 新建 `frontend/src/pages/LogCenter.tsx` + CSS 页面
12. 修改 `App.tsx` 添加路由
13. 修改 `Layout.tsx` 添加菜单项

### 阶段 4：验证
14. 启动前后端 → 访问 `/logs` → 手动产生各类日志 → 确认展示正确
15. 测试搜索、过滤、分页、展开折叠、复制功能

---

## 7. 待决策项

- [ ] MySQL 版本确认：是否支持 FULLTEXT ngram parser？如不支持，建表脚本需调整
- [ ] 日志保留策略：app_logs 表是否需要定期清理？保留多少天？
