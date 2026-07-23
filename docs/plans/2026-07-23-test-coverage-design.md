# 测试覆盖率看板 — 设计方案

> vLLM Ascend Dashboard · 2026-07-23
> 在「测试看板」（TestObservabilityDashboard）下新增覆盖率相关 Tab，展示两类覆盖率数据，并支持每小时定时刷新。

---

## 一、背景与目标

### 1.1 需求

1. **E2E 特性覆盖率**：vllm-ascend 仓库 `tests/e2e/coverage.html` 展示了 E2E 各特性测试的覆盖情况（146 个测试函数 × 架构/特性/并行/部署/硬件/量化/图模式 7 个维度）。需将该数据转入看板，在「测试看板」下新增 Tab 展示。
2. **PR 流水线覆盖率**：`https://vllm-ascend.obs.cn-north-4.myhuaweicloud.com/ci/precision-test/coverage.tar` 包含 PR 流水线测试用例的覆盖率信息。需新增 Tab 展示。
3. **定时刷新**：在现有调度任务中增加每小时检查这两个数据源是否有更新，有更新则刷新入库。

### 1.2 数据源摸底结论

#### 数据源 A：`tests/e2e/coverage.html`（来自本地 git clone）

- 由 `github_cache.py` 已克隆的 vllm-ascend 仓库提供，路径 `{cache_dir}/tests/e2e/coverage.html`，且仓库已由 `project_dashboard_cache_update` 任务每小时 pull 更新。
- 自包含 HTML，内嵌结构化 JS 数据：
  - `DATA` 数组：146 条测试记录，每条含 `filepath` / `test_name` / `card_count` / `models` / `coverage{}`（arch/feature/parallel/deploy/hardware/quantization/graph_mode 标签数组）。
  - `ALLOWED` 对象：7 个维度的合法取值分类法（taxonomy）。
  - 顶部摘要卡片：总数 146、已标记 9（6%）、1/2/4 卡数量。
- **解析方式**：正则提取 `DATA = [...]` 与 `const ALLOWED = {...}` 两个 JS 字面量，`json.loads` 转 Python 对象。无需第三方 HTML 解析库。

#### 数据源 B：`coverage.tar`（来自华为云 OBS）

- 体积 **233 MB**，解压后为 **原始 coverage.py 二进制数据**（非渲染 HTML 报告）。
- 结构：`vllm-ascend/VLLM-ASCEND@task_{ts}/<test_job>/covdata/coverage.linux-aarch64-{hw}-{cards}-{runner}-workflow.pid{pid}.{rand}.{rand}`
  - **121 个测试作业目录**，**483 个 covdata 文件**。
  - 每个 covdata 文件是 **SQLite 3 数据库**（coverage.py 7.15.2 格式），表：`file(id,path)` / `arc` / `line_bits` / `context` / `meta(version,sys_argv,when,has_arcs,hash)`。
  - 目录名编码测试路径：`tests__e2e__pull_request__one_card___310p__test_dense_model_310p` → `tests/e2e/pull_request/one_card/_310p/test_dense_model_310p`（`__`→`/`，`___`→`/_`）；部分带 `--test_func` 后缀表示单个测试函数。
  - covdata 文件名编码硬件/卡数：`a2b3-1`(A2 单卡) / `a3-2`(A3 双卡) / `a3-4`(A3 四卡) / `310p-1`(310P 单卡)。
  - `file.path` 形如 `/__w/vllm-ascend/vllm-ascend/vllm_ascend/__init__.py`（GitHub Actions runner 绝对路径）。

### 1.3 目标

- **E2E 覆盖 Tab**：原生 React 组件渲染（Ant Design），展示摘要卡片 + 维度筛选 + 测试矩阵表，与看板风格一致、受登录鉴权保护。
- **PR 流水线覆盖 Tab**：同时提供两种覆盖率视图：
  - **方案 1 覆盖广度矩阵**：按测试作业维度展示（测试路径/类型/硬件/卡数/运行次数/覆盖源码文件数/执行 arc 数/时间戳），并聚合「源码文件 ← 被哪些测试覆盖」反向矩阵与按模块统计。直接读 SQLite，无需 coverage 包，每小时可靠完成。
  - **方案 2 行覆盖率%**：在后端安装 `coverage` 包，combine 所有 covdata 后用本地 git clone 的源码作分母，生成每文件 statements/missing/covered/percent 与按模块汇总。较重，作为变更后的后台任务执行。
- **定时刷新**：每小时检查数据源变更（HTML 文件 hash / tar 的 Content-Length+ETag），仅变更时才重新解析入库。

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           数据源                                          │
│  ① vllm-ascend 本地 clone (github_cache)                                 │
│     tests/e2e/coverage.html                       ② 华为云 OBS            │
│         │                                         coverage.tar (233MB)   │
│         │ (每小时 pull 已有)                          │                   │
│         ▼                                         ▼ HTTP 条件请求         │
│ ┌───────────────────────┐         ┌──────────────────────────────────┐   │
│ │ E2ECoverageParser     │         │ PRCoverageCollector              │   │
│ │ 正则提取 DATA/ALLOWED │         │ HEAD 检查 → 下载 → tar 流式读取   │   │
│ └──────────┬────────────┘         │  ├ 方案1: 直接读 SQLite 汇总      │   │
│            │                      │  └ 方案2: coverage combine+report│   │
│            │                      │     (源码来自本地 clone, [paths]) │   │
│            │                      └──────────────┬───────────────────┘   │
│            ▼                                     ▼                       │
│ ┌──────────────────────────────────────────────────────────────────┐    │
│ │        ProjectDashboardConfig (JSON, 复用现有表)                  │    │
│ │  e2e_feature_coverage / pr_pipeline_coverage_breadth             │    │
│ │  pr_pipeline_coverage_lines / coverage_sync_status               │    │
│ └──────────────────────────────┬───────────────────────────────────┘    │
│                                ▼                                        │
│ ┌──────────────────────────────────────────────────────────────────┐    │
│ │  API: /api/v1/test-board/coverage/{e2e,pr-pipeline/breadth,      │    │
│ │       pr-pipeline/lines,status,sync}                             │    │
│ └──────────────────────────────┬───────────────────────────────────┘    │
│                                ▼                                        │
│ ┌──────────────────────────────────────────────────────────────────┐    │
│ │  前端 TestObservabilityDashboard                                   │
│ │  ├ Tab: E2E 特性覆盖 (原生 React)                                 │
│ │  └ Tab: PR 流水线覆盖 (内含 覆盖广度 + 行覆盖率 两个子区)          │
│ └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  调度：DataSyncScheduler 新增 _sync_coverage_job，每小时执行             │
└──────────────────────────────────────────────────────────────────────────┘
```

**核心思路**：
- 复用 `github_cache`（数据源 A 的文件已就绪）与 `ProjectDashboardConfig`（JSON 存储，与 support_matrix_sync 一致），不新建数据表。
- 数据源 B 用 HTTP 条件请求避免重复下载 233MB；方案 1 直接读 SQLite 摘要（快），方案 2 用 `coverage` 包 combine（慢，后台异步）。
- 新增一个调度任务统一驱动两类覆盖率，内部按数据源分别做变更检测。

---

## 三、数据模型（复用现有表，无新增表）

### 3.1 存储载体：`project_dashboard_config`

复用现有 `ProjectDashboardConfig(config_key, config_value JSON)` 表，新增 4 个 config_key：

| config_key | 内容 | 写入时机 |
|------------|------|----------|
| `e2e_feature_coverage` | E2E 特性覆盖完整数据 | HTML hash 变化时 |
| `pr_pipeline_coverage_breadth` | PR 覆盖广度矩阵 | tar 签名变化时 |
| `pr_pipeline_coverage_lines` | PR 行覆盖率% | tar 签名变化时（方案2完成后） |
| `coverage_sync_status` | 同步状态/最近检查时间/各源签名 | 每次调度执行后 |

### 3.2 各 JSON 结构定义

#### `e2e_feature_coverage`
```jsonc
{
  "summary": {
    "total_tests": 146,
    "marked_tests": 9,
    "marked_ratio": 0.06,
    "by_card": { "1": 86, "2": 34, "4": 26 }
  },
  "taxonomy": {                       // 即 ALLOWED
    "arch": ["classification","dense",...],
    "feature": [...], "parallel": [...], "deploy": [...],
    "hardware": [...], "quantization": [...], "graph_mode": [...]
  },
  "dim_labels": { "arch": "Architecture", "feature": "Feature", ... },
  "tests": [
    {
      "filepath": "one_card/test_qwen3_0_6b.py",
      "test_name": "test_dense_default_full_and_piecewise_graph",
      "card_count": 1,
      "models": ["Qwen/Qwen3-0.6B"],
      "coverage": {
        "arch": ["dense"], "feature": [], "parallel": ["TP"],
        "deploy": ["pd_mix"], "hardware": ["A2"],
        "quantization": ["BF16"], "graph_mode": ["full_and_piecewise"]
      },
      "is_marked": true
    }
  ],
  "source_file_hash": "sha256:...",     // HTML 文件内容 hash，用于变更检测
  "repo_commit": "abc1234",             // 生成该 HTML 时的仓库 commit
  "updated_at": "2026-07-23T...Z"
}
```

#### `pr_pipeline_coverage_breadth`（方案 1）
```jsonc
{
  "summary": {
    "task_id": "task_2026072223",
    "total_jobs": 121,
    "total_covdata_files": 483,
    "total_source_files_covered": 312,   // 全局去重源码文件数
    "total_arcs": 1280000,               // 全局 arc 总数（近似）
    "by_test_type": { "e2e": 95, "ut": 26 },
    "by_hardware": { "A2": 40, "A3": 60, "310P": 21 },
    "generated_when": "2026-07-22 19:50:05"  // meta.when 的最新值
  },
  "jobs": [
    {
      "job_dir": "tests__e2e__pull_request__one_card__test_attention_fa3",
      "test_path": "tests/e2e/pull_request/one_card/test_attention_fa3",
      "test_type": "e2e",                // e2e | ut
      "test_subpath": "pull_request/one_card/test_attention_fa3",
      "test_func": null,                 // 带 -- 后缀时为函数名
      "hardware": "A2", "card_count": 1,
      "covdata_count": 1,                // 该作业下 covdata 文件数（运行次数）
      "source_files_covered": 193,       // 该作业内去重 file.path 数
      "arcs": 10690,
      "latest_when": "2026-07-22 19:50:05",
      "sys_argv": "pytest ... test_attention_fa3.py"
    }
  ],
  "file_matrix": [                       // 反向矩阵：源码文件 → 覆盖它的作业
    {
      "source_path": "vllm_ascend/platform.py",   // 去掉 /__w/.../ 前缀
      "module": "vllm_ascend",                     // 顶层包
      "covered_by_jobs": 88,                       // 覆盖该文件的作业数
      "covered_by_hardware": ["A2","A3"]
    }
  ],
  "by_module": [                         // 按顶层包/二级模块聚合
    { "module": "vllm_ascend/patch/platform", "files": 12, "jobs_touching": 50 }
  ],
  "tar_signature": "len:233717760;etag:...;last_modified:...",
  "updated_at": "2026-07-23T...Z"
}
```

#### `pr_pipeline_coverage_lines`（方案 2）
```jsonc
{
  "totals": {
    "num_statements": 24500,
    "covered_lines": 18900,
    "missing_lines": 5600,
    "percent_covered": 77.1,            // coverage.py 头条（行+分支）
    "percent_statements_covered": 78.5, // 纯行覆盖率
    "num_branches": 8200,
    "covered_branches": 6100,
    "missing_branches": 2100,
    "num_partial_branches": 1800,
    "percent_branches_covered": 74.4,   // 纯分支覆盖率
    "num_files": 312
  },
  "by_module": [
    { "module": "vllm_ascend/patch/platform", "statements": 1200, "covered": 980, "percent": 81.7, "branches": 200, "covered_branches": 150, "files": 12 }
  ],
  "files": [
    {
      "path": "vllm_ascend/platform.py",
      "module": "vllm_ascend",
      "statements": 220, "missing": 30, "covered": 190,
      "percent_covered": 86.4,
      "has_branches": true,             // has_arcs=1
      "covered_by_jobs": 88          // 关联方案1的 file_matrix（可选）
    }
  ],
  "tar_signature": "len:233717760;...",
  "source_commit": "abc1234",        // 本地 clone 的 commit（分母来源，HEAD）
  "covdata_commit": "def5678",       // covdata 对应的源码 commit（推断，见 §4.3）
  "covdata_when": "2026-07-22T19:50:05Z", // covdata 生成时间（meta.when 最新值）
  "version_gap_commits": 42,         // source_commit 与 covdata_commit 的 commit 差距
  "version_gap_days": 1,             // 时间差距（天）
  "coverage_tool_version": "7.15.2", // covdata 的 coverage.py 版本（meta.version）
  "installed_coverage_version": "7.15.2", // 后端安装的 coverage 版本
  "updated_at": "2026-07-23T...Z",
  "status": "partial",               // ok | partial | failed；版本差距大时强制 partial
  "status_reason": "version_mismatch", // partial 的原因：version_mismatch | path_mapping | tool_version
  "error": null,
  "warning": "近似值：分母源码(HEAD)与覆盖率数据(commit def5678)存在 42 个 commit 偏差，行覆盖率仅供参考"
}
```

#### `coverage_sync_status`
```jsonc
{
  "last_check_at": "2026-07-23T...Z",
  "e2e": { "source_hash": "sha256:...", "updated_at": "...", "success": true, "error": null },
  "pr_breadth": { "tar_signature": "...", "updated_at": "...", "success": true, "error": null },
  "pr_lines": { "tar_signature": "...", "updated_at": "...", "success": true, "status": "ok", "error": null }
}
```

---

## 四、后端服务设计

新增服务文件 `backend/app/services/coverage_sync.py`，包含三类解析器 + 统一同步入口。

### 4.1 E2E 特性覆盖解析器

```python
class E2ECoverageParser:
    """从本地 git clone 读取 tests/e2e/coverage.html，解析 DATA 与 ALLOWED"""

    HTML_REL_PATH = "tests/e2e/coverage.html"
    # 维度固定，DIM_LABELS_JS 缺失时的兜底（已确认 HTML 中存在该变量）
    DIM_LABELS_FALLBACK = {
        "arch": "Architecture", "feature": "Feature", "parallel": "Parallel",
        "deploy": "Deploy", "hardware": "Hardware",
        "quantization": "Quantization", "graph_mode": "Graph Mode",
    }

    def parse(self) -> dict:
        cache = get_github_cache()
        # 不在此处 pull —— 依赖已有 project_dashboard_cache_update 每小时 pull job，
        # 避免与该 job 并发 pull 竞态（见检视意见 #5）
        html_path = cache.cache_dir / self.HTML_REL_PATH
        if not html_path.exists():
            raise FileNotFoundError(...)
        content = html_path.read_text(encoding="utf-8")
        # 主解析器：chompjs（容错强，专处理 JS 字面量→dict）；失败回退平衡括号计数
        data = self._extract_js_literal(content, "DATA", chompjs=True)
        allowed = self._extract_js_literal(content, "ALLOWED", chompjs=True)
        dim_labels = self._extract_js_literal(content, "DIM_LABELS_JS",
                                              fallback=self.DIM_LABELS_FALLBACK)
        summary = self._build_summary(data)        # total/marked/by_card
        tests = self._decorate_is_marked(data)     # 见下方 is_marked 定义
        return { "summary", "taxonomy", "dim_labels", "tests",
                 "source_file_hash", "repo_commit" }
```

**JS 字面量提取（双引擎）**：
- **主**：`chompjs` 库（`pip install chompjs`，纯 Python，专解析 JS 对象/数组字面量→Python dict，对换行/注释/尾逗号容错强）。先正则截取 `变量名 = ` 之后的字面量子串，再 `chompjs.parse_js_obj` / `parse_js_objects`。
- **备**：正则定位起止 + 字符串感知的平衡括号计数（跳过引号内 `]`/`}`），截取子串 `json.loads`。
- 任一引擎失败 → 记录 `success=false` 并保留旧数据，不覆盖。

**`is_marked` 定义**（检视意见 #7）：与 coverage.html 自身逻辑一致 —— `is_marked = any(coverage 各维度数组非空)`，即 `coverage` 字典中 arch/feature/parallel/deploy/hardware/quantization/graph_mode 任一存在且长度 > 0。

**变更检测**（检视意见 #5）：不在 parser 内 `cache.pull()`，改用 `cache.get_latest_commit()` 取本地 clone HEAD commit，与 `coverage_sync_status.e2e.repo_commit` 比较；commit 不变则跳过解析（HTML 随仓库 commit 变化）。`source_file_hash = sha256(content)` 作为二级校验。

### 4.2 PR 覆盖广度矩阵（方案 1：直接读 SQLite）

```python
class PRCoverageBreadthCollector:
    """流式读取 coverage.tar，逐个 covdata SQLite 汇总，不依赖 coverage 包"""

    TAR_URL = "https://vllm-ascend.obs.cn-north-4.myhuaweicloud.com/ci/precision-test/coverage.tar"

    async def collect(self) -> dict:
        sig = await self._head_signature()           # Content-Length + ETag + Last-Modified
        if sig == stored_sig: return {"skipped": True}
        tmp_tar = await self._download(sig)          # 流式下载到临时文件
        return self._process_tar(tmp_tar, sig)

    def _process_tar(self, tar_path, sig) -> dict:
        jobs = {}; file_map = {}  # path -> {jobs:set, hw:set}
        with tarfile.open(tar_path) as tar:
            for member in tar:
                if not member.name.endswith 分covdata 文件: continue
                tmp = extract_to_tmp(tar, member)
                stats = self._read_sqlite(tmp)       # file/path, arc count, meta.when/sys_argv
                job_dir = parse_job_dir(member)      # 解析测试路径/类型/函数
                hw, cards = parse_hw_from_filename(member.name)
                aggregate(jobs, file_map, job_dir, hw, cards, stats)
        return { "summary", "jobs", "file_matrix", "by_module", "tar_signature": sig }
```

**单文件 SQLite 读取**（检视意见 #5 — 安全性）：
```python
def _read_sqlite(self, path) -> dict:
    try:
        # 只读 + 查询超时，避免损坏文件挂死
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        files = [r[0] for r in con.execute("SELECT path FROM file LIMIT 10000")]
        arcs = con.execute("SELECT COUNT(*) FROM arc").fetchone()[0]
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        con.close()
        # 路径清洗：/__w/vllm-ascend/vllm-ascend/vllm_ascend/... -> vllm_ascend/...
        return { "files": cleaned_files, "arcs": arcs, "when": meta.get("when"), "sys_argv": meta.get("sys_argv") }
    except sqlite3.DatabaseError as e:
        logger.warning(f"Skip corrupt covdata {path}: {e}")  # 跳过损坏文件，继续处理其余
        return None
```
- 单查询 `LIMIT 10000` 防内存溢出；`timeout=5` 防挂死；`DatabaseError` 捕获后跳过该文件并记录。
- tar 下载后可选做整体 SHA256（与 `tar_signature` 一致即跳过解析）。

**路径解析规则**：
- `job_dir` → `test_path`：`tests__e2e__pull_request__one_card___310p__test_x` ⇒ `tests/e2e/pull_request/one_card/_310p/test_x`（`__`→`/`，`___`→`/_`）。
- `test_type`：路径前缀 `tests/e2e/` ⇒ `e2e`；`tests/ut/` ⇒ `ut`。
- `test_func`：`job_dir` 含 `--` 时取后半部分。
- 硬件：文件名 `linux-aarch64-{hw}-{cards}-` ⇒ `a2b3`→A2、`a3`→A3、`310p`→310P；`cards` 即卡数。

**性能**：483 个小 SQLite（单文件 <1MB，汇总仅 SELECT path / COUNT），整体 <1 分钟，可每小时稳定执行。

### 4.3 PR 行覆盖率%（方案 2：coverage 包 combine）

```python
class PRCoverageLineCollector:
    """用 coverage 包 combine 所有 covdata，结合本地源码生成行覆盖率"""

    async def collect(self, breadth_result) -> dict:
        # 复用 breadth 已下载的 tar，避免二次下载
        work_dir = mkdtemp()
        extract_all_covdata(tar_path, work_dir)      # 展开所有 covdata 文件
        rc = self._write_coveragerc(work_dir, cache.cache_dir)
        run("coverage", "combine", "--rcfile", rc, cwd=work_dir)  # 合并
        run("coverage", "json", "-o", "report.json",
            "--rcfile", rc, cwd=work_dir)            # 输出结构化 JSON
        return self._parse_coverage_json("report.json", breadth_result)
```

**`.coveragerc` 路径映射**（关键）：
```ini
[run]
source = vllm_ascend
[paths]
vllm_ascend =
    /__w/vllm-ascend/vllm-ascend/vllm_ascend/
    */vllm_ascend/
[report]
exclude_lines =
    pragma: no cover
    if __name__ == .__main__.:
    raise NotImplementedError
```
`[paths]` 将 covdata 中的 GitHub Actions 绝对路径 `/__w/vllm-ascend/vllm-ascend/vllm_ascend/` 重映射到本地 clone 的 `vllm_ascend/`，使 `coverage report` 能在本地源码上计算 `num_statements`（可执行行分母）。

**输出解析**：`coverage json` 产出 `coverage.json`，含 `totals`（num_statements/covered_lines/missing_lines/percent_covered）与 `files`（每文件同字段）。按 `path` 顶层包聚合 `by_module`。

**版本错配处理**（检视意见阻断 #1 — 关键）：
`[paths]` 只解决**路径重映射**，不解决**版本错配**：covdata 来自 PR 流水线某 commit X，本地 clone 源码是 HEAD(commit Y)。Y 新增文件无 covdata → 虚低为 0%；Y 删除文件 → 漏算；Y 改动文件 → 行号错配。**这是语义性失真，非路径问题。**

处理策略（透明标注 + 强制降级）：
1. **推断 covdata_commit**：从 `meta.when`（covdata 生成时间）取本地 clone `git log --before=<when> -1 --format=%H` 得到对应 commit；记录 `covdata_commit` / `covdata_when`。
2. **计算版本差距**：`version_gap_commits` = `git rev-list --count covdata_commit..source_commit`；`version_gap_days` = 时间差。
3. **强制 partial**：当 `version_gap_commits > 阈值(默认 20)` 或 `version_gap_days > 2` 时，`status=partial`、`status_reason=version_mismatch`，前端显著提示「近似值：分母源码(HEAD)与覆盖率数据存在 N 个 commit 偏差」。
4. **工具版本校验**：`meta.version`(covdata 的 coverage 版本) 与 `installed_coverage_version` 不一致时，`status=partial`、`status_reason=tool_version`，警告。
5. **未来增强（不在 P3）**：`git worktree add` 一个 covdata_commit 的源码副本做分母（准确但重），暂不实现，社区接受近似值后视需求推进。

**路径映射预校验**（检视意见 #4）：combine 前采样 1-2 个 covdata 的 `file.path`，验证经 `[paths]` 重映射后能在本地 clone 找到对应源码；映射失败（文件不存在比例高）则 `status=partial`、`status_reason=path_mapping` 并跳过 combine。

**降级与风险**：
- combine/report 超时（`PR_COVERAGE_LINE_TIMEOUT_SECONDS=600`）→ `status=failed`，保留上次成功结果，不阻塞方案 1。
- 仅当 tar 签名变化时才重跑；签名不变则跳过。
- 作为**独立后台任务**触发，不阻塞方案 1 的快速入库。

### 4.4 统一同步入口

```python
async def sync_all_coverage(db, source: str = "all") -> dict:
    """调度器/手动触发入口
    source: all | e2e | pr_breadth | pr_lines
    进程内 asyncio.Lock 串行化，避免手动+定时并发竞态（检视意见 #6）
    """
    async with _coverage_sync_lock:  # 模块级 asyncio.Lock()
        status = {}
        if source in ("all", "e2e"):
            status["e2e"] = await _sync_e2e(db)            # 快
        if source in ("all", "pr_breadth"):
            status["pr_breadth"] = await _sync_pr_breadth(db)  # 快
        if source in ("all", "pr_lines"):
            # 方案2：复用 breadth 的 tar；慢，独立后台执行
            status["pr_lines"] = await _sync_pr_lines(db)
        await _save_sync_status(db, status)
        return status
```
手动同步若遇锁占用 → API 返回 `409 Conflict {"error":"coverage sync in progress"}`。

---

## 五、调度任务设计

在 `DataSyncScheduler.start()` 中新增一个 IntervalTrigger 任务（每 60 分钟）：

```python
coverage_interval = getattr(settings, 'COVERAGE_SYNC_INTERVAL_MINUTES', 60)
self.scheduler.add_job(
    self._sync_coverage_job,
    trigger=IntervalTrigger(minutes=coverage_interval),
    id="coverage_sync",
    name="Test Coverage Sync",
    replace_existing=True,
)
```

```python
async def _sync_coverage_job(self) -> None:
    logger.info("COVERAGE SYNC JOB STARTED")
    async with SessionLocal() as db:
        try:
            from app.services.coverage_sync import sync_all_coverage
            result = await sync_all_coverage(db, source="all")
            logger.info(f"COVERAGE SYNC JOB COMPLETED - {result}")
        except Exception as e:
            logger.error(f"COVERAGE SYNC JOB FAILED: {e}", exc_info=True)
```

**变更检测策略**（避免无谓重算）：
- E2E：`cache.get_latest_commit()` 与存储 `repo_commit` 比较（commit 不变则跳过）；`sha256(coverage.html)` 作二级校验。
- PR：HTTP HEAD 获取 `Content-Length` + `ETag` + `Last-Modified` 组成 `tar_signature`（**已验证 OBS 端点 HEAD 返回 ETag/Last-Modified/Accept-Ranges**），与存储签名比较；一致则跳过下载与解析。
- 方案 2 行覆盖率：仅在 tar 签名变化且方案 1 完成后触发；用 `asyncio.create_task` 后台执行，不阻塞调度循环。

**下载安全**（检视意见阻断 #3）：
- 下载独立超时 `PR_COVERAGE_DOWNLOAD_TIMEOUT_SECONDS=300` + 流式写盘（`httpx stream` + `iter_raw`）。
- 重试 3 次，指数退避（30s/120s/300s）。
- 下载前校验磁盘剩余空间 ≥ 1GB（解压 483 SQLite 需临时空间，峰值约 500MB）。
- ECS(阿里云) → OBS(华为云 cn-north-4) 跨云，首次部署需实测下载耗时。

**配置项**（`config.py` 新增，`COVERAGE_SYNC_INTERVAL_MINUTES` 加 `ge=10` 校验 — 检视意见 #10）：
```python
COVERAGE_SYNC_INTERVAL_MINUTES: int = 60       # ge=10，避免过频
PR_COVERAGE_TAR_URL: str = "https://vllm-ascend.obs.cn-north-4.myhuaweicloud.com/ci/precision-test/coverage.tar"
PR_COVERAGE_DOWNLOAD_TIMEOUT_SECONDS: int = 300  # 下载超时
PR_COVERAGE_DOWNLOAD_RETRIES: int = 3            # 下载重试次数
PR_COVERAGE_LINE_ENABLED: bool = True            # 方案2开关，可关闭降级
PR_COVERAGE_LINE_TIMEOUT_SECONDS: int = 600      # 方案2 combine 超时
PR_COVERAGE_VERSION_GAP_THRESHOLD: int = 20      # commit 差距阈值，超则强制 partial
```

---

## 六、API 设计

在 `backend/app/api/v1/test_board.py` 中新增路由组（前缀已为 `/api/v1`，router prefix `/test-board`）：

| 方法 | 路径 | 说明 | 鉴权 |
|-----|------|------|------|
| GET | `/api/v1/test-board/coverage/e2e` | E2E 特性覆盖数据 | 登录用户 |
| GET | `/api/v1/test-board/coverage/pr-pipeline/breadth` | PR 覆盖广度矩阵（支持 `page/per_page/module/sort` 分页参数） | 登录用户 |
| GET | `/api/v1/test-board/coverage/pr-pipeline/lines` | PR 行覆盖率%（支持分页 + `format=csv` 导出） | 登录用户 |
| GET | `/api/v1/test-board/coverage/pr-pipeline/breadth?format=csv` | 广度矩阵 CSV 导出（检视意见 #8） | 登录用户 |
| GET | `/api/v1/test-board/coverage/status` | 同步状态（各源签名/最近更新/成功与否/版本差距） | 登录用户 |
| GET | `/api/v1/test-board/coverage/pr-pipeline/source?path=...` | 文件源码 + 逐行覆盖数据（§13 代码浏览器） | 登录用户 |
| POST | `/api/v1/test-board/coverage/sync` | 手动触发同步，body: `{source: "all"\|"e2e"\|"pr_breadth"\|"pr_lines"}` | **`CurrentAdminUser` 依赖**（检视意见阻断 #4） |

**鉴权**（检视意见阻断 #4）：`POST /coverage/sync` 必须用 `app.api.deps.CurrentAdminUser`（`deps.py:102`）依赖注入，**不复制**现有 `POST /test-board/sync` 的 inline `return {"error":...}` + HTTP 200 反模式。锁占用时返回 `409 Conflict`。

**分页与导出**（检视意见 #1、#8）：`breadth` 的 `file_matrix` 与 `lines` 的 `files` 在 API 层做 JSON 切片分页（`page/per_page`，默认 50），前端不全量加载；两接口均支持 `format=csv` 导出。当前数据量小（~312 源码文件，几十 KB），`ProjectDashboardConfig` 单行 JSON 可接受；若源码文件数增长超 ~2000，再迁移独立 `pr_coverage_files` 表（预留 escape hatch，不在本期建表）。

**响应示例 — `/coverage/status`**：
```json
{
  "last_check_at": "2026-07-23T08:00:00Z",
  "e2e": { "source_hash": "sha256:...", "updated_at": "...", "success": true, "repo_commit": "abc1234" },
  "pr_breadth": { "tar_signature": "len:233717760;etag:...", "updated_at": "...", "success": true },
  "pr_lines": { "tar_signature": "...", "updated_at": "...", "status": "ok", "percent_covered": 77.1 }
}
```

实现从 `ProjectDashboardConfig` 读取对应 config_key 返回；`/coverage/sync` 调用 `sync_all_coverage`，方案 2 走 `BackgroundTasks` 异步。

---

## 七、前端设计

### 7.1 服务与 Hooks

`frontend/src/services/testBoard.ts` 新增：
```typescript
export interface E2ECoverageData { summary; taxonomy; dim_labels; tests: E2ETestItem[]; updated_at; repo_commit }
export interface PRCoverageBreadth { summary; jobs: PRJobItem[]; file_matrix: PRFileItem[]; by_module; updated_at }
export interface PRCoverageLines { totals; by_module; files: PRLineFileItem[]; status; updated_at; source_commit }
export const getE2ECoverage = async (): Promise<E2ECoverageData> => ...
export const getPRCoverageBreadth = async (): Promise<PRCoverageBreadth> => ...
export const getPRCoverageLines = async (): Promise<PRCoverageLines> => ...
export const getCoverageSyncStatus = async (): Promise<CoverageSyncStatus> => ...
export const triggerCoverageSync = async (source): Promise<{success}> => ...
```

`frontend/src/hooks/useTestBoard.ts` 新增 `useE2ECoverage` / `usePRCoverageBreadth` / `usePRCoverageLines` / `useCoverageSyncStatus` / `useTriggerCoverageSync`（React Query，`refetchInterval: 600000`）。

### 7.2 页面改造 — `TestObservabilityDashboard.tsx`

在现有 `<Tabs>` 的 `items` 数组末尾追加 2 个 Tab（保持现有 4 个 Tab 不变）：

#### Tab 1：`e2e_coverage` — E2E 特性覆盖
- **摘要卡片**：总测试数 / 已标记数(占比+进度条) / 1·2·4 卡数量。
- **筛选工具条**：搜索框（test_name/filepath/model/tag）+ 卡数下拉 + 架构下拉 + 图模式下拉 + 「显示未标记」开关 + 导出 CSV。
- **测试矩阵表**（Ant Design Table）：按 card_count 分组（1/2/4 卡），列 File / Test / Models / Arch / Features / Parallel / Deploy / HW / Quant / Graph；coverage 标签用彩色 Tag 渲染；未标记行置灰。
- 维度下拉选项来自 `taxonomy`。

#### Tab 2：`pr_coverage` — PR 流水线覆盖
内部分两个 Card 区块（或二级 Tabs）：

- **区块 A：覆盖广度矩阵**（方案 1）
  - 摘要卡片：作业数 / covdata 文件数 / 覆盖源码文件数 / arc 总数 / by 硬件 / by 类型 / 生成时间。
  - 作业明细表：test_path / test_type / 硬件 / 卡数 / 运行次数 / 覆盖文件数 / arcs / 时间；支持搜索与按硬件/类型筛选。
  - 源码文件反向矩阵表：source_path / module / 被多少作业覆盖 / 覆盖硬件；可按 module 筛选、按覆盖作业数排序。

- **区块 B：行覆盖率**（方案 2）
  - 顶部汇总：总 statements / covered / missing / **总覆盖率%**（大数字+进度条）+ 状态标记（ok/partial/failed）。
  - **版本错配显著提示**（检视意见阻断 #1）：`status=partial` 且 `status_reason=version_mismatch` 时，醒目 Alert 显示「近似值：分母源码(HEAD `source_commit`)与覆盖率数据(`covdata_commit`)存在 `version_gap_commits` 个 commit / `version_gap_days` 天偏差，仅供参考」；`tool_version` 不一致也提示。
  - 显示 source_commit / covdata_commit / covdata_when / coverage 工具版本。
  - 按模块汇总表：module / statements / covered / percent（进度条）+ CSV 导出按钮。
  - 文件明细表：path / module / statements / missing / covered / percent；支持搜索与按 percent 排序、分页、CSV 导出。

两个 Tab 顶部均显示「最近更新时间 + 手动刷新按钮」（调用 `triggerCoverageSync`，成功后 invalidate query）；同步进行中按钮置 loading。

### 7.3 样式与术语
复用 `TestObservabilityDashboard.css` 的 stripe 风格；Tag 配色对齐 coverage.html 既有语义（arch=蓝、feature=粉、parallel=绿、deploy=黄、hardware=紫、quant=红、graph=青）。
**术语碰撞处理**（检视意见 minor）：现有首页雷达图「覆盖率」实为 owner 覆盖率（`TestHealthScore.coverage`，`test_board_service.py:83`），新增「测试覆盖率」Tab 易混淆。给雷达图「覆盖率」轴加 Tooltip「负责人覆盖率（已分配 owner 的用例占比）」以消歧。

---

## 八、依赖与配置变更

### 8.1 后端依赖
- **新增 `coverage`**（仅方案 2）：**版本 pin `coverage>=7.15.2,<8`**（检视意见阻断 #2 — covdata 为 7.15.2 格式，主版本变更可能不兼容），加入 `backend/pyproject.toml`。运行时校验 `meta.version` 与安装版本，不一致 `status=partial`。
- **新增 `chompjs`**（检视意见 #3 — E2E HTML 解析）：纯 Python 轻量库，容错强。
- SQLite 读取用标准库 `sqlite3`/`tarfile`；HTTP 下载用已有 `httpx`。

### 8.2 配置（`config.py` + `.env.example`）
```python
COVERAGE_SYNC_INTERVAL_MINUTES: int = 60       # ge=10 校验
PR_COVERAGE_TAR_URL: str = "https://vllm-ascend.obs.cn-north-4.myhuaweicloud.com/ci/precision-test/coverage.tar"
PR_COVERAGE_DOWNLOAD_TIMEOUT_SECONDS: int = 300
PR_COVERAGE_DOWNLOAD_RETRIES: int = 3
PR_COVERAGE_LINE_ENABLED: bool = True
PR_COVERAGE_LINE_TIMEOUT_SECONDS: int = 600
PR_COVERAGE_VERSION_GAP_THRESHOLD: int = 20
```

### 8.3 临时文件清理
- 下载的 tar 与解压目录用 `tempfile.TemporaryDirectory`，`try/finally` 确保删除；方案 2 的 combine 中间产物（`.coverage` 合并库可达数百 MB）在 `try/finally` 清理。
- **例外**：`coverage.json` 保留到 `data/coverage/coverage_{tar_sig_short}.json`，供站内代码浏览器按需读取逐行覆盖数据（见 §13.4）；旧签名文件在新签名入库后清理。

---

## 九、实现计划（分阶段）

| 阶段 | 任务 | 交付物 | 前置条件 |
|-----|------|--------|----------|
| P1 | 后端 E2E 解析器(chompjs) + API + 调度 + 前端 E2E Tab + 单测 | E2E 特性覆盖可看、每小时刷新 | 无阻断 |
| P2 | 后端方案1（广度矩阵）SQLite 读取 + API(分页/CSV) + 前端广度区块 + 单测 | PR 覆盖广度可看、每小时刷新 | 无阻断 |
| P3 | 后端方案2（行覆盖率%）coverage combine + 版本错配标注 + API + 前端行覆盖率区块 + 单测 | PR 行覆盖率%可看、变更后后台刷新 | **须先解决阻断 #1/#2/#3** |
| P4 | 联调、变更检测校验、降级路径、文档更新 | 全链路验证通过 | — |

**单元测试**（检视意见 #6 — 必须随代码提交）：`backend/tests/test_coverage_sync.py` + fixture：
- 小份 `coverage.html` 样本（含 DATA/ALLOWED/DIM_LABELS_JS）→ 测 chompjs 解析 + `is_marked` + summary。
- 格式变更样本（变量名改/缺 DIM_LABELS_JS）→ 测降级保留旧数据 + fallback 标签。
- mock covdata SQLite（正常/损坏）→ 测 `_read_sqlite` 跳过损坏 + 路径解码 `__`→`/`、`___`→`/_` + 硬件名解析。
- 版本差距计算 → 测 `status=partial` 强制降级。

**验收标准**：
- [ ] E2E Tab 展示 146 测试、筛选/搜索/导出 CSV 正常
- [ ] PR 广度 Tab 展示 121 作业、483 covdata 汇总、反向矩阵正确、CSV 导出
- [ ] PR 行覆盖率 Tab 展示总覆盖率%与按模块/文件明细；版本错配时显著提示「近似值」
- [ ] 每小时调度执行；数据源未变化时跳过、变化时刷新
- [ ] 手动刷新用 `CurrentAdminUser`；同步中返回 409；方案2失败不影响方案1
- [ ] `ruff` / `mypy` / `pytest`(含新单测) 通过；前端 `pnpm lint` / `tsc` 通过

---

## 十、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| coverage.html JS 字面量格式变更 | E2E 解析失败 | chompjs 主解析 + 平衡括号备选；失败保留旧数据 `success=false`；单测覆盖格式变更降级（检视意见 #3） |
| coverage.tar 体积大（233MB）跨云下载 | 带宽/磁盘/超时 | HEAD 签名不变则跳过下载；下载 300s 超时 + 3 次重试 + 流式写盘 + 磁盘空间预检（阻断 #3） |
| **方案2 版本错配**（covdata commit X vs 本地 HEAD） | 行覆盖率% 语义失真 | 显式标注 source_commit/covdata_commit/差距；超阈值强制 `status=partial` + 前端显著「近似值」提示；未来可 checkout 对应 commit（阻断 #1） |
| 方案2 路径映射不全 → statements=0 | 行覆盖率不准 | combine 前采样预校验 `[paths]`；失败 `status=partial/path_mapping`（检视意见 #4） |
| coverage 包版本不兼容 covdata | combine 静默失败 | `coverage>=7.15.2,<8` pin；版本不一致 `status=partial/tool_version`（阻断 #2） |
| 方案2 combine/report 超时 | 调度阻塞 | 独立后台任务 + 600s 超时；失败保留上次结果，不影响方案1 |
| 手动+定时同步并发竞态 | 重复下载/写冲突 | 进程内 `asyncio.Lock`；锁占用返回 409（检视意见 #6） |
| SQLite 损坏/恶意文件 | 解析崩溃/OOM | `mode=ro` + `timeout=5` + `LIMIT 10000` + 捕获 `DatabaseError` 跳过（检视意见 #5） |
| 本地 git clone 未就绪 | E2E/方案2源码缺失 | `get_latest_commit()` 失败时降级使用缓存版本并记录 |
| OBS 鉴权/限流 | PR 数据拉不到 | 记录错误、展示上次缓存数据并标注更新时间；重试退避 |

---

## 十一、与现有系统的关系

- **不新增数据表**：复用 `ProjectDashboardConfig`（与 `support_matrix_sync` 同模式）。
- **不新增前端路由**：在现有 `TestObservabilityDashboard` 页面内新增 Tab。
- **复用 github_cache**：E2E HTML 与方案2源码均来自本地 clone，无需额外拉取。
- **复用调度器**：在 `DataSyncScheduler` 中新增一个 job，与现有 test_board 相关 job 并列。
- **鉴权**：读取接口沿用 `get_current_user`；手动同步用 `CurrentAdminUser` 依赖（不复制 inline 反模式）。

---

## 十二、检视意见处理汇总

> 针对 issue #233 两轮检视意见（10 项 + maintainer 7 项阻断/非阻断）的逐条处理结论。所有事实性主张已核对代码库。

| # | 检视意见 | 处理结论 | 落地位置 |
|---|---------|---------|---------|
| **阻断1** | 方案2 版本错配（covdata commit X vs HEAD Y），`[paths]` 只重映射不解决版本差 | 采纳。显式标注 source_commit/covdata_commit/差距；超阈值强制 `status=partial`+前端显著「近似值」提示；checkout 对应 commit 列为未来增强 | §4.3、§7.2、§10 |
| **阻断2** | `coverage` 版本未 pin，covdata 7.15.2 格式 | 采纳。`coverage>=7.15.2,<8`；版本不一致 `status=partial/tool_version` | §8.1、§4.3 |
| **阻断3** | 233MB 跨云下载无超时/带宽评估；未验证 HEAD 语义 | 采纳。已验证 OBS HEAD 返回 ETag/Last-Modified/Accept-Ranges；下载 300s 超时+3 次重试+流式+磁盘预检 | §5、§4.2 |
| **阻断4** | 鉴权须用依赖注入，勿复制 inline 200 反模式 | 采纳。`POST /coverage/sync` 用 `CurrentAdminUser`(`deps.py:102`) | §6 |
| 中1 | 大 JSON 存 ProjectDashboardConfig 性能 | 部分采纳。实际仅 ~312 文件/几十 KB（maintainer 亦认可可接受），本期不建表；API 层分页切片 + 超 2000 迁独立表 escape hatch | §6 |
| 中2 | 233MB 全量下载 | 采纳。短期待 300s 超时+重试；中期推动 CI 发布轻量 summary.json；长期 CI 推送 | §5、§10 |
| 中3 | 正则解析 JS 脆弱 | 采纳。chompjs 主解析 + 平衡括号备选 + 失败保留旧数据；中期推动上游生成 coverage.json | §4.1、§8.1 |
| 中4 | `[paths]` 映射脆弱 | 采纳。combine 前采样预校验，失败降级 partial | §4.3 |
| 中5 | SQLite 只读未校验完整性 | 采纳。`timeout=5`+`LIMIT`+`DatabaseError` 跳过 | §4.2 |
| 中6 | sync 竞态 | 采纳。`asyncio.Lock`+409 | §4.4 |
| 低7 | `is_marked` 未说明 | 采纳。明确为「任一 coverage 维度非空」，对齐 HTML 自身逻辑 | §4.1 |
| 低8 | PR 覆盖缺 CSV 导出 | 采纳。breadth/lines 均支持 `format=csv` | §6、§7.2 |
| 低9 | coverage 版本兼容 | 同阻断2 | §8.1 |
| 低10 | 调度间隔上限 | 采纳。`COVERAGE_SYNC_INTERVAL_MINUTES` 加 `ge=10` | §5 |
| 非5 | parser 内 pull 与现有 job 重复竞态 | 采纳。移除 parser 内 pull，改 `get_latest_commit()` 变更检测 | §4.1 |
| 非6 | 单测策略缺失 | 采纳。`tests/test_coverage_sync.py`+fixture 随代码提交 | §9 |
| 非7 | DIM_LABELS_JS 未验证存在 | 已验证存在（HTML 中确认）；加硬编码 fallback | §4.1 |
| minor | 术语碰撞 `TestHealthScore.coverage` | 采纳。雷达图「覆盖率」加 Tooltip「负责人覆盖率」 | §7.3 |
| minor | `.coverage` 大文件清理 | 采纳。`try/finally` 清理 | §8.3 |

**推进路径**：P1(E2E)、P2(广度) 无阻断可立即开工；P3(行覆盖率) 须先完成阻断 #1/#2/#3 的实现；全程遵守阻断 #4(鉴权)与 #6(单测)。

---

## 十三、覆盖率数据 ↔ 社区代码跳转关联 + 数据染色

> 需求：覆盖率数据能与 vllm-ascend 社区源码跳转关联，并实现覆盖数据染色显示。

### 13.1 可行性结论（已验证）

| 能力 | 可行性 | 依据 |
|------|--------|------|
| 文件级跳转 GitHub | ✅ | 路径已知 + commit 已跟踪（`repo_commit` / `covdata_commit`），拼 `github.com/vllm-project/vllm-ascend/blob/{commit}/{path}` |
| 逐行覆盖染色（含分支） | ✅ | `coverage json` 输出每文件 `executed_lines`/`missing_lines`/`excluded_lines`/**`missing_branches`**/`executed_branches` + 分支统计（已实测，coverage.py 7.x）。covdata `has_arcs=1`，分支数据完整 |
| 源码内容获取（准确对齐行号） | ✅ | 本地 clone 为 `--filter=blob:none` 部分克隆，**含完整 commit 历史**（`github_cache.py:108`）；`git show {covdata_commit}:{path}` 可取任意 commit 源码；近期 covdata commit 的 blob 已在本地 |

**与 coverage.py 的兼容性**（已实测 `coverage json` 输出）：聚合 `percent_covered` 即 coverage.py 报告头条数字（含行+分支），完全一致；逐行视图需渲染**分支部分覆盖（partial）**才能与 coverage.py HTML 报告逐字对齐 —— 见 §13.2 Layer 2。

**关键洞察**：站内代码浏览器用 **`covdata_commit` 的源码**（非 HEAD）渲染，使逐行覆盖与源码行号**精确对齐** —— 这让「逐行视图」不受 §4.3 版本错配影响；版本错配警告只影响聚合 `%`（用 HEAD 做分母）。即：单文件逐行视图是准确的，聚合百分比是近似的。

### 13.2 三层设计

#### Layer 1：文件级跳转链接（E2E + PR 覆盖）

| 数据源 | 链接对象 | GitHub URL |
|--------|---------|------------|
| E2E 特性覆盖 | 测试文件 `filepath`（如 `one_card/test_qwen3_0_6b.py`） | `blob/{repo_commit}/tests/e2e/pull_request/{filepath}` |
| PR 广度矩阵 | 源码文件 `source_path`（如 `vllm_ascend/platform.py`） | `blob/{covdata_commit}/{source_path}` |
| PR 行覆盖率 | 文件 `path` | `blob/{covdata_commit}/{path}` |

文件名列渲染为可点击链接（外链图标），`target=_blank` 打开 GitHub。commit 取自各数据快照已记录的 `repo_commit` / `covdata_commit`。

> E2E 覆盖是**特性/标签覆盖**（哪些测试覆盖哪些特性维度），非行覆盖，故 E2E 仅做文件级 GitHub 跳转，不做逐行染色。逐行染色仅 PR 行覆盖率（方案2）。

#### Layer 2：站内代码浏览器 + 逐行染色（PR 行覆盖率）

点击 PR 行覆盖率的文件行 → 打开 `CoverageCodeViewer` Drawer：

- **源码**：`git show {covdata_commit}:{path}` 获取（准确对齐）；失败回退 HEAD 源码并标注「行号可能错位」。
- **逐行染色**（与 coverage.py HTML 报告**逐字对齐**，含分支部分覆盖；无语法高亮，纯覆盖着色）：
  - 🟩 绿色背景：`executed_lines` 且**无 missing branch**（完全覆盖）
  - 🟧 琥珀色背景：`executed_lines` **但存在 missing_branches**（行已执行，但从该行的某分支未走 —— coverage.py 的 partial `!` 行）
  - 🟥 红色背景：`missing_lines`（未执行）
  - 行号列 + 文件级 `percent_covered`
- **分支标注**（对齐 coverage.py）：partial 行右侧标注缺失分支，如 `line 2: → 5`（`missing_branches` 中 `[2,5]`）；行尾可展开列出该行所有 missing branch。
- **顶部信息栏**：文件路径 + `covdata_commit`（短）+ 覆盖率%（coverage.py 头条 `percent_covered`，含行+分支）+ **行覆盖率 `percent_statements_covered` / 分支覆盖率 `percent_branches_covered`** 分项 + 「在 GitHub 查看」按钮 + 「复制路径」。
- 渲染：`<pre>` + 每行一个 `<div>` 带背景色，行号左列；不引入语法高亮依赖（前端无 highlight/prism/shiki，保持轻量）。

**partial 判定规则**（与 coverage.py 一致）：某行 ∈ `executed_lines` 且该行是 `missing_branches` 中某个 `[from, to]` 的 `from` → 标记为 amber/partial。

#### Layer 3：聚合数据染色（热力图）

文件列表 / 模块汇总表的 `percent_covered` 单元格按梯度背景染色（coverage.py 头条数字，含行+分支；可调阈值，默认）：
- 🔴 红 `< 50%` / 🟡 黄 `50–80%` / 🟢 绿 `≥ 80%`
- 文字颜色保证对比度（深底浅字）。进度条保留，叠加单元格底色形成热力图效果。
- 文件列表额外展示 `has_branches` 标记；可切换列显示「行覆盖率」/「分支覆盖率」分项（与 coverage.py 一致）。

### 13.3 后端 API

新增文件源码接口（鉴权：登录用户）：

```
GET /api/v1/test-board/coverage/pr-pipeline/source?path=vllm_ascend/platform.py
```
响应：
```jsonc
{
  "path": "vllm_ascend/platform.py",
  "commit": "def5678",              // covdata_commit
  "source": "import ...\n...",      // git show {commit}:{path} 内容
  "executed_lines": [1,2,3,5],
  "missing_lines": [10,11,15],
  "excluded_lines": [],
  "executed_branches": [[1,2],[2,3]],   // 分支（has_arcs=1 时存在）
  "missing_branches": [[2,5]],           // partial 行判定依据
  "summary": {
    "percent_covered": 86.4,             // coverage.py 头条（行+分支）
    "percent_statements_covered": 88.0,  // 纯行覆盖率
    "percent_branches_covered": 82.0,    // 纯分支覆盖率
    "num_statements": 220, "covered_lines": 190, "missing_lines": 30,
    "num_branches": 40, "covered_branches": 33, "missing_branches": 7
  },
  "github_url": "https://github.com/vllm-project/vllm-ascend/blob/def5678/vllm_ascend/platform.py",
  "source_aligned": true            // false=回退 HEAD 源码，行号可能错位
}
```
- 源码：`github_cache` 执行 `git show {covdata_commit}:{path}`（`subprocess`，`timeout=10`）；失败回退读 HEAD 文件，`source_aligned=false`。
- 逐行 + 分支数据：从磁盘 `coverage.json`（见 13.4）的 `files[path]` 读取（`executed_lines`/`missing_lines`/`excluded_lines`/`executed_branches`/`missing_branches`/`summary` 原样透传）。
- `has_arcs=0` 的文件无 `*_branches` 字段，前端仅渲染行级三色（绿/红/灰）。
- 路径白名单：仅允许 `vllm_ascend/` 前缀，防路径穿越（`..`/绝对路径拒绝）。

GitHub URL 拼接由前端完成（commit + path 已知），无需额外接口。

### 13.4 存储调整

- 方案2 combine 后**保留** `coverage.json` 到磁盘 `data/coverage/coverage_{tar_sig_short}.json`（原 §8.3 改为「combine 中间产物 `.coverage` 清理；`coverage.json` 保留供代码浏览器按需读取」）。
- DB 的 `pr_pipeline_coverage_lines` 仍只存聚合 stats + `files[]`（不含逐行数组，避免 JSON 膨胀）；逐行数据按需从磁盘 JSON 读。
- 记录 `coverage_json_path` 与 `covdata_commit` 于 `pr_pipeline_coverage_lines`，供源码接口定位。

### 13.5 前端组件

- 新增 `CoverageCodeViewer.tsx`（Drawer）：props `{ path, commit }`，调用 `getCoverageSource(path)`，渲染逐行染色 `<pre>`。
- `useCoverageSource(path)` hook（React Query，`enabled: !!path`）。
- 文件列表/模块表：路径列加 `<Button type="link" icon={<CodeOutlined/>}>` → 打开 Drawer；旁置 GitHub 外链图标。
- percent 单元格：封装 `CoverageHeatCell` 组件，按阈值染色。
- E2E 测试矩阵：`filepath` 列加 GitHub 外链图标（`repo_commit` 拼接）。

### 13.6 实现归属

| 阶段 | 关联功能 |
|------|---------|
| P1 | E2E 测试文件 GitHub 跳转链接（Layer 1） |
| P2 | PR 广度矩阵源码文件 GitHub 跳转链接（Layer 1） |
| P3 | PR 行覆盖率：`CoverageCodeViewer` 逐行染色（Layer 2）+ 文件/模块热力图染色（Layer 3）+ 保留 coverage.json + `/source` API |

**验收追加**：
- [ ] E2E/PR 文件路径可跳转 GitHub 对应 commit 源码
- [ ] PR 行覆盖率点击文件打开站内代码浏览器，逐行染色与 coverage.py HTML 报告一致（绿完全覆盖 / 琥珀 partial 分支 / 红未执行 / 灰排除）
- [ ] partial 行标注缺失分支（如 `line 2: → 5`），与 coverage.py `!` 标记对齐
- [ ] 聚合 % 与 coverage.py 头条一致；展示行覆盖率/分支覆盖率分项
- [ ] 文件/模块表 percent 单元格热力图染色
- [ ] `git show` 失败时回退 HEAD 并标注 `source_aligned=false`
