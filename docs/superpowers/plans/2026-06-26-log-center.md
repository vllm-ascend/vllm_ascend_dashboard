# 日志中心实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建统一的日志中心页面（Datadog 风格），聚合展示 Claude CLI 日志、Failure Analysis 报告、应用日志、调度器日志，支持过滤、搜索、分页。

**Architecture:** 后端新建统一日志查询 API（`/api/v1/logs`），从文件系统和 MySQL 多源聚合日志；前端新建 LogCenter 页面，左过滤面板 + 右日志流布局，antd Table virtual 滚动。

**Tech Stack:** FastAPI + SQLAlchemy + MySQL, React + TypeScript + Ant Design + @tanstack/react-query

## Global Constraints

- MySQL 生产数据库（需兼容 FULLTEXT ngram parser，或 LIKE 兜底）
- 前端需登录访问（ProtectedRoute）
- 样式遵循项目现有 Stripe 设计主题
- 不重启/暂停正在运行的后端服务
- 遵循项目现有代码模式：Pydantic schemas、React Query hooks、upgrade script 迁移

---

## File Map

| File | Operation | Responsibility |
|------|-----------|----------------|
| `backend/scripts/upgrade_v0.0.19.py` | Create | DB migration: create `app_logs` table |
| `backend/app/core/logging.py` | Create | DB log handler: intercept Python logging → MySQL |
| `backend/app/main.py` | Modify | Register DB log handler + log API router |
| `backend/app/schemas/logs.py` | Create | Pydantic schemas |
| `backend/app/services/log_service.py` | Create | Multi-source log aggregation, search, pagination |
| `backend/app/api/v1/logs.py` | Create | FastAPI routes |
| `frontend/src/services/logs.ts` | Create | Axios API client |
| `frontend/src/hooks/useLogs.ts` | Create | React Query hooks |
| `frontend/src/components/LogEntry.tsx` | Create | Expandable log entry component |
| `frontend/src/pages/LogCenter.tsx` | Create | Main log center page |
| `frontend/src/pages/LogCenter.css` | Create | Page styles |
| `frontend/src/App.tsx` | Modify | Add `/logs` route |
| `frontend/src/components/Layout.tsx` | Modify | Add "日志中心" sidebar menu item |

---

### Task 1: Database Migration — app_logs table

**Files:**
- Create: `backend/scripts/upgrade_v0.0.19.py`

**Interfaces:**
- Produces: MySQL table `app_logs(id, timestamp, level, module, function_name, line_number, message, traceback, created_at)` with indexes `idx_app_logs_timestamp`, `idx_app_logs_level`, `idx_app_logs_module`

- [ ] **Step 1: Write the migration script**

Create `backend/scripts/upgrade_v0.0.19.py` following the existing pattern from `upgrade_v0.0.18.py`. The script must:

1. Use the same boilerplate (imports, `check_table_exists`, async `upgrade()`)
2. Try MySQL DDL first: `CREATE TABLE app_logs` with `FULLTEXT INDEX ft_app_logs_message (message) WITH PARSER ngram`, `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4`
3. Catch exception → fallback to plain index (no FULLTEXT)
4. Catch again → SQLite fallback
5. Ensure indexes: `idx_app_logs_timestamp`, `idx_app_logs_level`, `idx_app_logs_module`
6. Set `DESCRIPTION = "Add app_logs table for unified log center"`

Columns:
- `id BIGINT AUTO_INCREMENT PRIMARY KEY`
- `timestamp DATETIME(3) NOT NULL`
- `level VARCHAR(10) NOT NULL`
- `module VARCHAR(200)`
- `function_name VARCHAR(200)`
- `line_number INT`
- `message TEXT NOT NULL`
- `traceback TEXT`
- `created_at DATETIME DEFAULT CURRENT_TIMESTAMP`

- [ ] **Step 2: Run the migration**

```bash
cd backend && python scripts/upgrade_v0.0.19.py
```
Expected: `[OK] Upgrade to v0.0.19 completed successfully!`

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/upgrade_v0.0.19.py
git commit -m "feat: add app_logs table for unified log center"
```

---

### Task 2: DB Log Handler

**Files:**
- Create: `backend/app/core/logging.py`

**Interfaces:**
- Produces: `setup_db_logging()` — call once at app startup; installs a `logging.Handler` that writes to `app_logs` via a background `asyncio.Queue` worker

- [ ] **Step 1: Write `backend/app/core/logging.py`**

Implementation outline:

```python
"""Database-backed logging handler. Non-blocking queue-based writes."""

import logging
import queue
import traceback
from datetime import UTC, datetime
from sqlalchemy import text
from app.db.base import SessionLocal

_log_queue: queue.Queue = queue.Queue(maxsize=10000)

class DBLogHandler(logging.Handler):
    def emit(self, record):
        # Build entry dict {timestamp, level, module, function_name, line_number, message, traceback}
        # Put into _log_queue; drop on queue.Full
        pass

async def _db_log_worker():
    # Loop: drain _log_queue in batches of up to 100, INSERT into app_logs via SessionLocal
    pass

async def _flush_batch(entries):
    # INSERT each entry into app_logs table using text() SQL
    pass

_worker_started = False

def setup_db_logging():
    # Idempotent. Installs DBLogHandler on root logger. Starts _db_log_worker as asyncio task.
    pass
```

Key details:
- `DBLogHandler.emit()`: extract `record.created`, `record.levelname`, `record.name`, `record.funcName`, `record.lineno`, `self.format(record)`, `traceback.format_exc()` if `record.exc_info`
- Timestamp format: `"%Y-%m-%d %H:%M:%S.%f"[:-3]`
- Worker drains queue with `get(timeout=1)` then `get_nowait()` for up to 99 more
- `_flush_batch` uses `SessionLocal()` context manager, commits per batch, rollback on error
- `setup_db_logging` uses a `_worker_started` flag for idempotency; gets running loop via `asyncio.get_running_loop()`

- [ ] **Step 2: Verify imports work**

```bash
cd backend && python -c "from app.core.logging import setup_db_logging; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/logging.py
git commit -m "feat: add DB log handler for persisting app logs"
```

---

### Task 3: Register DB Log Handler in main.py

**Files:**
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `setup_db_logging` from `app.core.logging`

- [ ] **Step 1: Add import**

In `backend/app/main.py`, add near other `from app...` imports:

```python
from app.core.logging import setup_db_logging
```

- [ ] **Step 2: Call in lifespan**

In the `lifespan()` function, add right after `logger.info("Starting vLLM Ascend Dashboard application...")`:

```python
setup_db_logging()
```

- [ ] **Step 3: Verify app imports**

```bash
cd backend && python -c "from app.main import app; print('OK, routes:', len(app.routes))"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register DB log handler on startup"
```

---

### Task 4: Log Schemas

**Files:**
- Create: `backend/app/schemas/logs.py`
- Modify: `backend/app/schemas/__init__.py`

**Interfaces:**
- Produces:
  - `TimeRange(start, end)` — optional datetime range
  - `LogQueryRequest(sources, levels, time_range, search, page, page_size)` — query filters
  - `LogEntryMetadata(...)` — per-source metadata with `ConfigDict(extra="allow")`
  - `LogEntryResponse(id, source, level, timestamp, summary, content, metadata)`
  - `LogQueryResponse(total, page, page_size, entries: list[LogEntryResponse])`
  - `LogSourceInfo(key, label, count, last_entry)`
  - `LogSourcesResponse(sources: list[LogSourceInfo])`

- [ ] **Step 1: Write `backend/app/schemas/logs.py`**

Create all Pydantic models listed above. Key details:
- `LogEntryMetadata`: all fields optional; `model_config = ConfigDict(extra="allow")` so per-source fields don't cause validation errors
- `LogQueryRequest.page` default=1, ge=1; `page_size` default=50, ge=1, le=200
- `LogEntryResponse.summary` default `""`, `content` default `""`, `metadata` default factory

- [ ] **Step 2: Update `backend/app/schemas/__init__.py`**

Add to `__all__`:
```python
"LogQueryRequest", "LogEntryResponse", "LogQueryResponse",
"LogSourceInfo", "LogSourcesResponse",
```

Add import at bottom:
```python
from .logs import (
    LogQueryRequest, LogEntryResponse, LogQueryResponse,
    LogSourceInfo, LogSourcesResponse,
)
```

- [ ] **Step 3: Verify**

```bash
cd backend && python -c "from app.schemas import LogQueryRequest, LogEntryResponse; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/logs.py backend/app/schemas/__init__.py
git commit -m "feat: add log center Pydantic schemas"
```

---

### Task 5: Log Service

**Files:**
- Create: `backend/app/services/log_service.py`

**Interfaces:**
- Consumes: schemas from `app.schemas.logs`
- Produces:
  - `LogService.get_sources(db) -> LogSourcesResponse`
  - `LogService.query(filters: LogQueryRequest, db) -> LogQueryResponse`
  - `LogService.get_entry(log_id: str, db) -> LogEntryResponse | None`

- [ ] **Step 1: Write `backend/app/services/log_service.py`**

Implementation outline (full ~280 lines):

```python
"""Multi-source log aggregation service."""

class LogService:
    async def get_sources(self, db) -> LogSourcesResponse:
        # Count files in data/claude_logs/ → claude_cli count
        # Count .md files under data/failure-analysis/ → failure_analysis count
        # SELECT COUNT(*) FROM app_logs → app count
        # SELECT COUNT(*) FROM app_logs WHERE module LIKE '%scheduler%' → scheduler count
        pass

    async def query(self, filters, db) -> LogQueryResponse:
        # 1. Determine active_sources and active_levels from filters (default: all)
        # 2. Collect entries from each active source:
        #    - claude_cli: scan data/claude_logs/ date dirs, parse .log files
        #    - failure_analysis: walk data/failure-analysis/, parse .md files
        #    - app/scheduler: SQL query app_logs with WHERE conditions
        # 3. Merge, sort by timestamp DESC
        # 4. Apply search filter (Python-level for file sources; SQL-level for DB)
        # 5. Paginate in memory and return LogQueryResponse
        pass

    async def get_entry(self, log_id, db) -> LogEntryResponse | None:
        # Parse log_id: "{source}:{rest}"
        # Route to appropriate reader based on source
        pass
```

Helper functions (private to module):
- `_parse_cli_log_file(filepath) -> LogEntryResponse | None`: Parse structured CLI log text; extract provider/model/route/duration/exit_code from header lines; summary = first 200 chars of STDOUT section; level = "error" if exit_code != 0 else "info"; ID = `claude_cli:{date_dir}:{filename_stem}`; timestamp from file mtime
- `_parse_failure_analysis_file(filepath) -> LogEntryResponse | None`: Extract workflow_name/job_name/job_id from path structure `failure-analysis/<wf>/<job>/<id>.md`; summary = first 200 chars; ID = `failure_analysis:{wf}:{job}:{id}`

Search strategy:
- For MySQL sources: use `MATCH(message) AGAINST(:kw IN BOOLEAN MODE) OR message LIKE :kw_like`; catch exceptions and fall back to LIKE-only
- For file sources: Python string `in` check against summary + content

Pagination: collect all matching entries → sort → slice `[start:end]` in Python. DB fetches `page_size * 3` rows to allow for merge-sort with file sources.

- [ ] **Step 2: Verify imports**

```bash
cd backend && python -c "from app.services.log_service import LogService; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/log_service.py
git commit -m "feat: add multi-source log query service"
```

---

### Task 6: Log API Routes

**Files:**
- Create: `backend/app/api/v1/logs.py`

**Interfaces:**
- Consumes: `LogService`, schemas from `app.schemas.logs`
- Produces: `router` (APIRouter) with 3 endpoints

- [ ] **Step 1: Write `backend/app/api/v1/logs.py`**

```python
"""Log Center API Routes."""
from fastapi import APIRouter, HTTPException, status
from urllib.parse import unquote
from app.api.deps import DbSession
from app.schemas.logs import LogQueryRequest, LogQueryResponse, LogSourcesResponse, LogEntryResponse
from app.services.log_service import LogService

router = APIRouter()

@router.get("/sources", response_model=LogSourcesResponse)
async def list_log_sources(db: DbSession):
    return await LogService().get_sources(db)

@router.post("/query", response_model=LogQueryResponse)
async def query_logs(filters: LogQueryRequest, db: DbSession):
    return await LogService().query(filters, db)

@router.get("/{log_id:path}", response_model=LogEntryResponse)
async def get_log_entry(log_id: str, db: DbSession):
    entry = await LogService().get_entry(unquote(log_id), db)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Log entry not found: {log_id}")
    return entry
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/v1/logs.py
git commit -m "feat: add log center API routes"
```

---

### Task 7: Register Log Routes in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add import**

In the `from app.api.v1 import (...)` block, add `logs` to the tuple.

- [ ] **Step 2: Add router**

After the last `app.include_router(...)` call, add:
```python
app.include_router(logs.router, prefix="/api/v1/logs", tags=["日志中心"])
```

- [ ] **Step 3: Verify**

```bash
cd backend && python -c "from app.main import app; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: register log center API routes"
```

---

### Task 8: Frontend API Service

**Files:**
- Create: `frontend/src/services/logs.ts`

**Interfaces:**
- Produces TypeScript types: `LogQueryRequest`, `LogEntryMetadata`, `LogEntry`, `LogQueryResponse`, `LogSource`, `LogSourcesResponse`
- Produces functions: `getLogSources()`, `queryLogs(filters)`, `getLogEntry(logId)`

- [ ] **Step 1: Write `frontend/src/services/logs.ts`**

Follow existing pattern from `frontend/src/services/ci.ts`:
- Import `api` from `./api`
- Define all TypeScript interfaces matching the backend Pydantic schemas
- Export three async functions using `api.get` / `api.post`
- `getLogEntry`: URL-encode the log_id with `encodeURIComponent`

- [ ] **Step 2: Commit**

```bash
git add frontend/src/services/logs.ts
git commit -m "feat: add log center frontend API service"
```

---

### Task 9: Frontend Hooks

**Files:**
- Create: `frontend/src/hooks/useLogs.ts`

**Interfaces:**
- Produces: `useLogSources()`, `useLogQuery(filters)`, `useLogEntry(logId)` — all React Query hooks

- [ ] **Step 1: Write `frontend/src/hooks/useLogs.ts`**

Follow existing pattern from `frontend/src/hooks/useCI.ts`:
- `useLogSources`: `queryKey: ['log-sources']`, `refetchInterval: 60000`
- `useLogQuery`: `queryKey: ['log-query', filters]`, `placeholderData: (prev) => prev`
- `useLogEntry`: `queryKey: ['log-entry', logId]`, `enabled: !!logId`

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useLogs.ts
git commit -m "feat: add log center React Query hooks"
```

---

### Task 10: LogEntry Component

**Files:**
- Create: `frontend/src/components/LogEntry.tsx`

**Interfaces:**
- Consumes: `LogEntry` type from `../services/logs`
- Produces: `<LogEntryRow entry={...}>` — expandable log row

- [ ] **Step 1: Write `frontend/src/components/LogEntry.tsx`**

Key design:
- Collapsed row: `[timestamp] [LEVEL tag] [SOURCE tag] [summary text...] [copy icon] [expand arrow]`
- Expanded: metadata tags row + `<pre>` block with dark background (#1e1e1e), max-height 480px, monospace font
- Level colors: error=red, warning=orange, info=blue, debug=default
- Source labels: claude_cli="CLI", failure_analysis="分析", app="应用", scheduler="调度"
- Copy button copies `entry.content` to clipboard
- Click row to toggle expand/collapse
- Hover: light gray background (#fafafa)

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/LogEntry.tsx
git commit -m "feat: add expandable LogEntry component"
```

---

### Task 11: LogCenter Page + Styles

**Files:**
- Create: `frontend/src/pages/LogCenter.tsx`
- Create: `frontend/src/pages/LogCenter.css`

- [ ] **Step 1: Write `frontend/src/pages/LogCenter.css`**

Styles for:
- `.log-center`: flex row, full height (`calc(100vh - 64px - 48px)`)
- `.log-center-sidebar`: 280px, dark background (#1a1a2e), white text, scrollable
- `.log-center-main`: flex column, white background
- `.log-toolbar`: flex row, sticky top, gray background (#fafafa)
- `.log-list-container`: flex 1, scrollable
- `.log-pagination`: centered, border-top
- Dark sidebar overrides for Ant Checkbox/Radio components

- [ ] **Step 2: Write `frontend/src/pages/LogCenter.tsx`**

Component structure:
```
LogCenter
├── div.log-center-sidebar
│   ├── Checkbox.Group (sources: Claude CLI / 失败分析 / 应用日志 / 调度器)
│   ├── Divider
│   ├── Checkbox.Group (levels: ERROR / WARNING / INFO / DEBUG)
│   ├── Divider
│   ├── Radio.Group (time presets: 1h / 24h / 7d / custom)
│   ├── [if custom] RangePicker
│   ├── Divider
│   └── Source stats (count per source from useLogSources)
└── div.log-center-main
    ├── div.log-toolbar
    │   ├── Input.Search (with 300ms debounce)
    │   └── Total count display
    ├── div.log-list-container
    │   └── LogEntryRow[] (or Spin / Empty)
    └── div.log-pagination
        └── Pagination (showSizeChanger, showQuickJumper)
```

State management:
- `selectedSources: string[]` (default all)
- `selectedLevels: string[]` (default error/warning/info)
- `timePreset: string` (default '24h')
- `customRange: [Dayjs, Dayjs] | null`
- `searchText: string` → debounced 300ms → `debouncedSearch`
- `page: number`, `pageSize: number`

On any filter change → reset `page` to 1
Build `LogQueryRequest` with `useMemo` from all filter state
Pass to `useLogQuery(queryFilters)`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/LogCenter.tsx frontend/src/pages/LogCenter.css
git commit -m "feat: add LogCenter page with Datadog-style layout"
```

---

### Task 12: Route + Menu Integration

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Add route in App.tsx**

Add import:
```tsx
import LogCenter from './pages/LogCenter'
```

Add route inside the protected layout `<Route>` (after test-board route):
```tsx
<Route path="logs" element={<LogCenter />} />
```

- [ ] **Step 2: Add menu item in Layout.tsx**

Add `ReadOutlined` to the icon imports.

In `menuItems` array, add after test-board item:
```tsx
{ key: '/logs', icon: <ReadOutlined />, label: '日志中心' },
```

In `mobileMenuItems`, add:
```tsx
{ key: '/logs', icon: <ReadOutlined />, label: '日志中心' },
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat: add /logs route and sidebar menu item"
```

---

### Task 13: End-to-End Verification

- [ ] **Step 1: Run DB migration**

```bash
cd backend && python scripts/upgrade_v0.0.19.py
```
Expected: `[OK] Upgrade to v0.0.19 completed successfully!`

- [ ] **Step 2: Test API — sources**

```bash
curl -s http://localhost:8000/api/v1/logs/sources | python -m json.tool | head -20
```
Expected: JSON with `sources` array

- [ ] **Step 3: Test API — query**

```bash
curl -s -X POST http://localhost:8000/api/v1/logs/query \
  -H 'Content-Type: application/json' \
  -d '{"page": 1, "page_size": 5}' | python -m json.tool | head -30
```
Expected: JSON with `total`, page info, and `entries`

- [ ] **Step 4: Open frontend at `http://localhost:5173/logs`**

Expected: Left sidebar with filters + stats, main area with log stream, search + pagination

- [ ] **Step 5: Interact — filter, search, expand, copy, paginate**

- [ ] **Step 6: Fix any issues and commit**

---

## Execution Notes

- Tasks 1-3 (DB infrastructure) must run sequentially
- Tasks 4-7 (backend API) can partially overlap but prefer sequential
- Tasks 8-9 (frontend data layer) independent of backend tasks, can run in parallel with 4-7
- Tasks 10-12 (frontend UI) depend on 8-9; must be sequential
- Task 13 (verification) is last
