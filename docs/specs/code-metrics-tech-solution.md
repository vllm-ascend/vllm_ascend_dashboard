# vllm-ascend 代码度量看板 — 技术方案设计

> 版本：v1.0 | 日期：2026-07-09 | 作者：架构组
> 度量对象：vllm-ascend 仓库（C++ 52.7% + Python 42.0%）

## 第一章 系统架构

### 1.1 整体架构

系统分为五层：采集层（工具链）、采集服务层、存储层（5张表）、业务服务层、API/前端层。架构图见 `code-metrics-architecture.mermaid`。

### 1.2 与现有系统集成

| 现有模块 | 集成方式 |
|----------|----------|
| GitHubLocalCache | 复用 — 获取 vllm-ascend 本地仓库路径，git checkout 切换版本 |
| DataSyncScheduler | 扩展 — 新增 2 个定时任务 |
| PullRequest | 读取 — 聚合 PR 变更量（衍生指标） |
| DailyDataFileStore | 读取 — 聚合 Commit 文件变更（热力图） |
| CommitAnalysisFileStore | 读取 — 聚合修改类型分布 |
| CIResult/CIJob | 读取 — 关联 CI 通过率 |

### 1.3 数据流

采集：GitHubLocalCache.update_repo() → git checkout target_ref → cloc/lizard/jscpd/ruff/mypy/cppcheck/clang-tidy/grep → 解析 JSON → 写入 5 张表
查询：前端 → API → CodeMetricsService → 读取快照/明细表 → 返回 JSON

## 第二章 度量指标体系设计

### 2.1 第一类：代码规模

| 指标 | Cmetrics对应 | 计算方式 | 采集工具 | 适用语言 |
|------|-------------|----------|----------|----------|
| total_loc | code_size | 删除空行注释后有效行数 | cloc | 通用 |
| total_raw_lines | raw_lines | 物理行数（含空行注释） | cloc | 通用 |
| loc_python | — | Python 代码行 | cloc | Python |
| loc_cpp | — | C++ 代码行 | cloc | C++ |
| loc_c | — | C 代码行 | cloc | C |
| loc_cmake | — | CMake 代码行 | cloc | CMake |
| loc_shell | — | Shell 代码行 | cloc | Shell |
| loc_vllm_ascend | — | vllm_ascend/ 模块行数 | cloc | 模块级 |
| loc_csrc | — | csrc/ 模块行数 | cloc | 模块级 |
| loc_tests | — | tests/ 模块行数 | cloc | 模块级 |
| loc_benchmarks | — | benchmarks/ 模块行数 | cloc | 模块级 |
| loc_tools | — | tools/ 模块行数 | cloc | 模块级 |
| loc_docs | — | docs/ 模块行数 | cloc | 模块级 |
| total_functions | methods_total | 函数/方法总数 | lizard | Python+C++ |
| total_files | files_total | 源码文件总数 | cloc | 通用 |

### 2.2 第二类：圈复杂度

| 指标 | Cmetrics对应 | 计算方式 | 采集工具 | 适用语言 |
|------|-------------|----------|----------|----------|
| cc_total | cyclomatic_complexity_total | 圈复杂度总和 | lizard | Python+C++ |
| cc_per_method | cyclomatic_complexity_per_method | 平均圈复杂度 | 计算 | Python+C++ |
| cc_maximum | maximum_cyclomatic_complexity | 最大圈复杂度 | lizard | Python+C++ |
| cc_huge_count | huge_cyclomatic_complexity_total | CC>15(Python)/CC>20(C++)的函数数 | lizard | Python+C++ |
| cc_huge_ratio | huge_cyclomatic_complexity_ratio | 超大复杂度函数占比 | 计算 | Python+C++ |
| cc_adequacy | cyclomatic_complexity_adequacy | 满足度=(functions-huge)/functions×100% | 计算 | Python+C++ |

### 2.3 第三类：嵌套深度

| 指标 | Cmetrics对应 | 计算方式 | 采集工具 | 适用语言 |
|------|-------------|----------|----------|----------|
| max_depth | maximum_depth | 最大嵌套深度 | lizard | Python+C++ |
| depth_huge_count | huge_depth_total | 深度>5的函数数 | lizard | Python+C++ |
| depth_huge_ratio | huge_depth_ratio | 超大深度函数占比 | 计算 | Python+C++ |

### 2.4 第四类：函数体量

| 指标 | Cmetrics对应 | 计算方式 | 采集工具 | 适用语言 |
|------|-------------|----------|----------|----------|
| method_lines_total | method_lines | 函数总行数 | lizard | Python+C++ |
| lines_per_method | lines_per_method | 函数平均行数 | 计算 | Python+C++ |
| huge_method_count | huge_method_total | 行数>80的函数数 | lizard | Python+C++ |
| huge_method_ratio | huge_method_ratio | 超大函数占比 | 计算 | Python+C++ |
| huge_file_count | huge_non_headerfile_total | 行数>500的文件数 | cloc | 通用 |
| huge_headerfile_count | huge_headerfile_total | 行数>500的C++头文件数 | cloc | C++专用 |

### 2.5 第五类：代码重复率

| 指标 | Cmetrics对应 | 计算方式 | 采集工具 | 适用语言 |
|------|-------------|----------|----------|----------|
| dup_blocks | code_duplication_total | 重复代码块数 | jscpd | 通用 |
| dup_lines | — | 重复代码行数 | jscpd | 通用 |
| dup_ratio | code_duplication_ratio | 重复率=dup_lines/total_loc×100% | 计算 | 通用 |
| dup_files | file_duplication_total | 含重复代码的文件数 | jscpd | 通用 |

### 2.6 第六类：安全与规范

| 指标 | Cmetrics对应 | 计算方式 | 采集工具 | 适用语言 |
|------|-------------|----------|----------|----------|
| todo_count | redundant_code_total | TODO/FIXME/HACK/XXX 注释数 | grep | 通用 |
| todo_kloc | redundant_code_kloc | 技术债务密度=todo_count/total_loc×1000 | 计算 | 通用 |
| type_check_errors | — | mypy 类型检查错误数 | mypy | Python |
| lint_errors | warning_suppression_total | ruff+cppcheck 错误数 | ruff+cppcheck | Python+C++ |
| lint_warnings | — | ruff+cppcheck 警告数 | ruff+cppcheck | Python+C++ |
| unsafe_functions_count | unsafe_functions_total | C++危险函数调用数(memcpy/strcpy/sprintf/gets等) | cppcheck+grep | C++专用 |
| unsafe_functions_kloc | unsafe_functions_kloc | 危险函数千行密度 | 计算 | C++专用 |
| warning_suppression_count | warning_suppression_total | #pragma warning 抑制数 | grep | C++专用 |
| warning_suppression_kloc | warning_suppression_kloc | 告警抑制千行密度 | 计算 | C++专用 |

### 2.7 C++ 专用指标启用说明

vllm-ascend 的 csrc/ 目录占 52.7% 是 C++ 代码，以下 Cmetrics C/C++ 专用指标适用：
- `huge_headerfile_total/ratio`：C++ 头文件(.h/.hpp)行数>500 的文件数，csrc/ 中有大量头文件
- `unsafe_functions_total/kloc`：C++ 危险函数（memcpy/strcpy/strcat/sprintf/gets/scanf 等），cppcheck 可检测
- `warning_suppression_total/kloc`：`#pragma warning` 和 `#pragma GCC diagnostic` 抑制数

### 2.8 衍生指标

| 指标 | 来源 | 说明 |
|------|------|------|
| pr_size_distribution | PullRequest.additions+deletions | 小型(<100)/中型(100-500)/大型(>500) PR 分布 |
| code_churn_rate | DailyCommit.additions+deletions | 每日代码变更量趋势 |
| change_type_distribution | CommitAnalysis.change_type | Feature/Bugfix/Refactor/Test/CI 分布 |
| file_hotspot_top20 | DailyCommit.files_changed | 变更频率最高 Top 20 文件 |
| contributor_activity | DailyCommit.author | 贡献者活跃度排行 |
| ci_pass_rate_by_pr_size | CIResult×PullRequest | 不同 PR 大小的 CI 通过率 |

## 第三章 数据模型设计

### 3.1 CodeMetricsSnapshot

```python
class CodeMetricsSnapshot(Base):
    """代码度量快照（每日采集一次）"""
    __tablename__ = "code_metrics_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    repo = Column(String(100), nullable=False)  # vllm-ascend
    branch = Column(String(100), default="main")
    commit_sha = Column(String(40))
    ref_type = Column(String(20), default="branch")  # branch/tag/commit
    ref_value = Column(String(100))  # 分支名/tag名/commit sha

    # === 第一类：代码规模 ===
    total_loc = Column(Integer)
    total_raw_lines = Column(Integer)
    loc_python = Column(Integer)
    loc_cpp = Column(Integer)
    loc_c = Column(Integer)
    loc_cmake = Column(Integer)
    loc_shell = Column(Integer)
    loc_vllm_ascend = Column(Integer)
    loc_csrc = Column(Integer)
    loc_tests = Column(Integer)
    loc_benchmarks = Column(Integer)
    loc_tools = Column(Integer)
    loc_docs = Column(Integer)
    total_functions = Column(Integer)
    total_files = Column(Integer)

    # === 第二类：圈复杂度 ===
    cc_total = Column(Integer)
    cc_per_method = Column(Float)
    cc_maximum = Column(Integer)
    cc_huge_count = Column(Integer)
    cc_huge_ratio = Column(Float)
    cc_adequacy = Column(Float)

    # === 第三类：嵌套深度 ===
    max_depth = Column(Integer)
    depth_huge_count = Column(Integer)
    depth_huge_ratio = Column(Float)

    # === 第四类：函数体量 ===
    method_lines_total = Column(Integer)
    lines_per_method = Column(Float)
    huge_method_count = Column(Integer)
    huge_method_ratio = Column(Float)
    huge_file_count = Column(Integer)
    huge_headerfile_count = Column(Integer)  # C++ 专用

    # === 第五类：重复率 ===
    dup_blocks = Column(Integer)
    dup_lines = Column(Integer)
    dup_ratio = Column(Float)
    dup_files = Column(Integer)

    # === 第六类：安全与规范 ===
    todo_count = Column(Integer)
    todo_kloc = Column(Float)
    type_check_errors = Column(Integer)
    lint_errors = Column(Integer)
    lint_warnings = Column(Integer)
    unsafe_functions_count = Column(Integer)   # C++ 专用
    unsafe_functions_kloc = Column(Float)      # C++ 专用
    warning_suppression_count = Column(Integer) # C++ 专用
    warning_suppression_kloc = Column(Float)    # C++ 专用

    # === 衍生指标 ===
    pr_count = Column(Integer)
    pr_avg_size = Column(Float)
    code_churn = Column(Integer)
    commit_count = Column(Integer)
    contributor_count = Column(Integer)

    # === 综合评分 ===
    health_score = Column(Float)
    health_grade = Column(String(5))  # A/B/C/D

    collection_duration = Column(Float)
    collection_status = Column(String(20))  # success/partial/failed
    error_message = Column(Text)

    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint('snapshot_date', 'repo', 'branch', 'ref_value', name='uq_metrics_snapshot'),
    )
```

### 3.2 CodeComplexityDetail

```python
class CodeComplexityDetail(Base):
    """函数级复杂度明细"""
    __tablename__ = "code_complexity_details"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("code_metrics_snapshots.id"), index=True)
    repo = Column(String(100), nullable=False)

    file_path = Column(String(500), nullable=False)
    function_name = Column(String(200), nullable=False)
    start_line = Column(Integer)
    language = Column(String(20))  # python / cpp

    cyclomatic_complexity = Column(Integer)
    nesting_depth = Column(Integer)
    function_lines = Column(Integer)
    parameter_count = Column(Integer)

    is_huge_cc = Column(Boolean, default=False)
    is_huge_depth = Column(Boolean, default=False)
    is_huge_method = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
```

### 3.3 CodeDuplicationDetail

```python
class CodeDuplicationDetail(Base):
    """重复代码明细"""
    __tablename__ = "code_duplication_details"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("code_metrics_snapshots.id"), index=True)

    source_file = Column(String(500), nullable=False)
    source_start_line = Column(Integer)
    target_file = Column(String(500), nullable=False)
    target_start_line = Column(Integer)
    duplicate_lines = Column(Integer)
    code_fragment = Column(Text)

    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
```

### 3.4 FileChangeHeatmap

```python
class FileChangeHeatmap(Base):
    """文件变更热力图"""
    __tablename__ = "file_change_heatmap"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), nullable=False)
    file_path = Column(String(500), nullable=False)

    change_count_7d = Column(Integer, default=0)
    change_count_30d = Column(Integer, default=0)
    change_count_90d = Column(Integer, default=0)
    additions_30d = Column(Integer, default=0)
    deletions_30d = Column(Integer, default=0)
    bug_fix_count_30d = Column(Integer, default=0)
    contributors_30d = Column(JSON)

    last_changed_at = Column(TIMESTAMP)
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint('repo', 'file_path', name='uq_file_heatmap'),
    )
```

### 3.5 CodeSecurityDetail（新增 — C++ 安全问题明细）

```python
class CodeSecurityDetail(Base):
    """C++ 安全问题明细"""
    __tablename__ = "code_security_details"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("code_metrics_snapshots.id"), index=True)

    file_path = Column(String(500), nullable=False)
    line_number = Column(Integer)
    issue_type = Column(String(50), nullable=False)  # unsafe_function / warning_suppression
    severity = Column(String(20))  # error / warning / info
    message = Column(String(500))
    function_name = Column(String(200))  # 危险函数名或抑制指令
    tool = Column(String(50))  # cppcheck / clang-tidy / grep

    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
```

### 3.6 代码健康度评分算法

```python
def calculate_code_health_score(snapshot: CodeMetricsSnapshot) -> tuple[float, str]:
    """
    六维加权评分模型（0-100）：
    1. 复杂度维度 (25%): cc_adequacy
    2. 重复率维度 (20%): 100 - dup_ratio × 5
    3. 规范维度 (20%): 100 - lint_density × 10
    4. 体量维度 (15%): 100 - huge_method_ratio × 3
    5. 技术债务维度 (10%): 100 - todo_kloc × 5
    6. C++安全维度 (10%): 100 - unsafe_functions_kloc × 10
    """
    complexity_score = snapshot.cc_adequacy or 0
    duplication_score = max(0, 100 - (snapshot.dup_ratio or 0) * 5)

    if snapshot.total_loc and snapshot.total_loc > 0:
        lint_density = (snapshot.lint_errors or 0) / snapshot.total_loc * 1000
        lint_score = max(0, 100 - lint_density * 10)
    else:
        lint_score = 0

    method_size_score = max(0, 100 - (snapshot.huge_method_ratio or 0) * 3)
    debt_score = max(0, 100 - (snapshot.todo_kloc or 0) * 5)
    cpp_security_score = max(0, 100 - (snapshot.unsafe_functions_kloc or 0) * 10)

    score = (
        complexity_score * 0.25
        + duplication_score * 0.20
        + lint_score * 0.20
        + method_size_score * 0.15
        + debt_score * 0.10
        + cpp_security_score * 0.10
    )

    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    else:
        grade = "D"

    return round(score, 1), grade
```

## 第四章 数据采集服务设计

### 4.1 采集工具链

| 工具 | 用途 | 安装方式 | 支持语言 |
|------|------|----------|----------|
| cloc | 代码行数统计 | apt install cloc | 全语言 |
| lizard | 圈复杂度+嵌套深度+函数行数 | pip install lizard | Python/C++/Java/JS等 |
| jscpd | 代码重复检测 | npm install jscpd | 全语言 |
| ruff | Python Lint | pip install ruff | Python |
| mypy | Python 类型检查 | pip install mypy | Python |
| cppcheck | C++ 静态分析 | apt install cppcheck | C/C++ |
| clang-tidy | C++ 静态分析 | apt install clang-tidy | C/C++ |
| cpplint | C++ 代码规范 | pip install cpplint | C++ |
| grep | TODO/FIXME 统计 | 系统自带 | 通用 |

### 4.2 CodeMetricsCollector 采集服务

```python
class CodeMetricsCollector:
    """代码度量采集器（每日定时执行）"""

    def __init__(self, db: AsyncSession, repo_name: str = "vllm-ascend"):
        self.db = db
        self.repo_name = repo_name
        self.github_cache = get_github_cache()  # 复用现有 GitHubLocalCache

    async def collect(self, snapshot_date: date, ref_type: str = "branch",
                       ref_value: str = "main") -> CodeMetricsSnapshot:
        """执行全量采集"""
        # 1. 确保仓库已克隆并更新
        self.github_cache.ensure_repo_cloned()
        self.github_cache.update_repo()
        repo_path = str(self.github_cache.cache_dir)

        # 2. 切换到目标版本
        await self._checkout_ref(repo_path, ref_type, ref_value)
        commit_sha = await self._get_head_sha(repo_path)

        # 3. 幂等检查
        existing = await self._check_existing(snapshot_date, ref_value)
        if existing:
            # 删除旧快照及关联明细
            await self._delete_snapshot(existing)

        snapshot = CodeMetricsSnapshot(
            snapshot_date=snapshot_date, repo=self.repo_name,
            branch=ref_value, ref_type=ref_type, ref_value=ref_value,
            commit_sha=commit_sha,
        )

        try:
            await self._collect_loc(snapshot, repo_path)
            await self._collect_complexity(snapshot, repo_path)
            await self._collect_duplication(snapshot, repo_path)
            await self._collect_lint(snapshot, repo_path)
            await self._collect_tech_debt(snapshot, repo_path)
            await self._collect_security(snapshot, repo_path)
            await self._collect_derived_metrics(snapshot, snapshot_date)
            snapshot.health_score, snapshot.health_grade = calculate_code_health_score(snapshot)
            snapshot.collection_status = "success"
        except Exception as e:
            snapshot.collection_status = "partial"
            snapshot.error_message = str(e)

        self.db.add(snapshot)
        await self.db.commit()
        return snapshot

    async def _checkout_ref(self, repo_path: str, ref_type: str, ref_value: str):
        """git checkout 到目标版本"""
        if ref_type == "tag":
            cmd = ["git", "-C", repo_path, "checkout", f"tags/{ref_value}"]
        elif ref_type == "commit":
            cmd = ["git", "-C", repo_path, "checkout", ref_value]
        else:
            cmd = ["git", "-C", repo_path, "checkout", ref_value]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()

    async def _collect_loc(self, snapshot, repo_path):
        """使用 cloc 统计代码行数 — 采集 vllm-ascend 仓库各目录"""
        # 全仓库统计
        result = await self._run_cloc(repo_path)
        snapshot.total_loc = result.get("SUM", {}).get("code", 0)
        snapshot.total_raw_lines = result.get("SUM", {}).get("total", 0)
        snapshot.total_files = result.get("SUM", {}).get("files", 0)
        snapshot.loc_python = result.get("Python", {}).get("code", 0)
        snapshot.loc_cpp = result.get("C++", {}).get("code", 0)
        snapshot.loc_c = result.get("C", {}).get("code", 0)
        snapshot.loc_cmake = result.get("CMake", {}).get("code", 0)
        snapshot.loc_shell = result.get("Bourne Shell", {}).get("code", 0)

        # 按模块统计
        for module, field in [("vllm_ascend", "loc_vllm_ascend"), ("csrc", "loc_csrc"),
                              ("tests", "loc_tests"), ("benchmarks", "loc_benchmarks"),
                              ("tools", "loc_tools"), ("docs", "loc_docs")]:
            mod_result = await self._run_cloc(f"{repo_path}/{module}")
            setattr(snapshot, field, mod_result.get("SUM", {}).get("code", 0))

    async def _collect_complexity(self, snapshot, repo_path):
        """使用 lizard 分析 Python + C++ 函数"""
        # Python: lizard vllm_ascend/ -l python
        py_cc = await self._run_lizard(f"{repo_path}/vllm_ascend", "python")
        # C++: lizard csrc/ -l cpp
        cpp_cc = await self._run_lizard(f"{repo_path}/csrc", "cpp")
        # tests 目录也分析
        test_cc = await self._run_lizard(f"{repo_path}/tests", "python")

        all_functions = py_cc["functions"] + cpp_cc["functions"] + test_cc["functions"]
        cc_values = [f["cyclomatic_complexity"] for f in all_functions]
        depth_values = [f["nesting_depth"] for f in all_functions]
        line_values = [f["line_count"] for f in all_functions]

        snapshot.total_functions = len(all_functions)
        snapshot.cc_total = sum(cc_values)
        snapshot.cc_per_method = snapshot.cc_total / max(snapshot.total_functions, 1)
        snapshot.cc_maximum = max(cc_values) if cc_values else 0

        CC_THRESHOLD_PY = 15
        CC_THRESHOLD_CPP = 20
        def is_huge_cc(f):
            threshold = CC_THRESHOLD_CPP if f.get("language") == "cpp" else CC_THRESHOLD_PY
            return f["cyclomatic_complexity"] > threshold

        snapshot.cc_huge_count = sum(1 for f in all_functions if is_huge_cc(f))
        snapshot.cc_huge_ratio = snapshot.cc_huge_count / max(snapshot.total_functions, 1) * 100
        snapshot.cc_adequacy = (snapshot.total_functions - snapshot.cc_huge_count) / max(snapshot.total_functions, 1) * 100

        snapshot.max_depth = max(depth_values) if depth_values else 0
        DEPTH_THRESHOLD = 5
        snapshot.depth_huge_count = sum(1 for d in depth_values if d > DEPTH_THRESHOLD)
        snapshot.depth_huge_ratio = snapshot.depth_huge_count / max(snapshot.total_functions, 1) * 100

        snapshot.method_lines_total = sum(line_values)
        snapshot.lines_per_method = snapshot.method_lines_total / max(snapshot.total_functions, 1)
        METHOD_LINES_THRESHOLD = 80
        snapshot.huge_method_count = sum(1 for l in line_values if l > METHOD_LINES_THRESHOLD)
        snapshot.huge_method_ratio = snapshot.huge_method_count / max(snapshot.total_functions, 1) * 100

        # 保存超大函数明细
        for f in all_functions:
            if is_huge_cc(f) or f["nesting_depth"] > DEPTH_THRESHOLD or f["line_count"] > METHOD_LINES_THRESHOLD:
                detail = CodeComplexityDetail(
                    repo=self.repo_name, file_path=f["file_path"],
                    function_name=f["name"], start_line=f["start_line"],
                    language=f.get("language", "python"),
                    cyclomatic_complexity=f["cyclomatic_complexity"],
                    nesting_depth=f["nesting_depth"], function_lines=f["line_count"],
                    parameter_count=f.get("parameter_count", 0),
                    is_huge_cc=is_huge_cc(f),
                    is_huge_depth=f["nesting_depth"] > DEPTH_THRESHOLD,
                    is_huge_method=f["line_count"] > METHOD_LINES_THRESHOLD,
                )
                self.db.add(detail)

    async def _collect_duplication(self, snapshot, repo_path):
        """使用 jscpd 检测代码重复"""
        result = await self._run_jscpd(repo_path)
        snapshot.dup_blocks = result.get("statistics", {}).get("totalClones", 0)
        snapshot.dup_lines = result.get("statistics", {}).get("totalLines", 0)
        snapshot.dup_files = result.get("statistics", {}).get("totalFiles", 0)
        snapshot.dup_ratio = snapshot.dup_lines / max(snapshot.total_loc, 1) * 100

        for dup in sorted(result.get("duplicates", []), key=lambda x: x.get("lines", 0), reverse=True)[:50]:
            detail = CodeDuplicationDetail(
                source_file=dup["firstFile"]["name"], source_start_line=dup["firstFile"]["start"],
                target_file=dup["secondFile"]["name"], target_start_line=dup["secondFile"]["start"],
                duplicate_lines=dup["lines"], code_fragment=dup.get("fragment", "")[:500],
            )
            self.db.add(detail)

    async def _collect_lint(self, snapshot, repo_path):
        """执行 ruff + mypy (Python) + cppcheck (C++)"""
        # Python: ruff vllm_ascend/
        ruff_result = await self._run_ruff(f"{repo_path}/vllm_ascend")
        # Python: mypy vllm_ascend/
        mypy_result = await self._run_mypy(f"{repo_path}/vllm_ascend")
        # C++: cppcheck csrc/
        cppcheck_result = await self._run_cppcheck(f"{repo_path}/csrc")

        snapshot.lint_errors = ruff_result["errors"] + cppcheck_result["errors"]
        snapshot.lint_warnings = ruff_result["warnings"] + cppcheck_result["warnings"]
        snapshot.type_check_errors = mypy_result["errors"]

    async def _collect_tech_debt(self, snapshot, repo_path):
        """统计 TODO/FIXME/HACK/XXX 注释"""
        result = await self._run_grep_tech_debt(repo_path)
        snapshot.todo_count = result["count"]
        snapshot.todo_kloc = result["count"] / max(snapshot.total_loc, 1) * 1000

    async def _collect_security(self, snapshot, repo_path):
        """C++ 安全分析 — 危险函数 + 告警抑制"""
        # 危险函数检测：cppcheck + grep
        unsafe_result = await self._run_grep_unsafe_functions(f"{repo_path}/csrc")
        snapshot.unsafe_functions_count = unsafe_result["count"]
        snapshot.unsafe_functions_kloc = unsafe_result["count"] / max(snapshot.loc_cpp or 1, 1) * 1000

        # 告警抑制检测：grep #pragma warning / #pragma GCC diagnostic
        suppress_result = await self._run_grep_warning_suppression(f"{repo_path}/csrc")
        snapshot.warning_suppression_count = suppress_result["count"]
        snapshot.warning_suppression_kloc = suppress_result["count"] / max(snapshot.loc_cpp or 1, 1) * 1000

        # 保存安全问题明细
        for item in unsafe_result["items"]:
            detail = CodeSecurityDetail(
                file_path=item["file"], line_number=item["line"],
                issue_type="unsafe_function", severity="warning",
                message=item["message"], function_name=item["function"],
                tool="grep",
            )
            self.db.add(detail)

    async def _collect_derived_metrics(self, snapshot, snapshot_date):
        """从已有数据聚合衍生指标"""
        pr_stats = await self._query_pr_stats(snapshot_date)
        snapshot.pr_count = pr_stats["count"]
        snapshot.pr_avg_size = pr_stats["avg_size"]
        snapshot.code_churn = await self._query_code_churn(snapshot_date)
        snapshot.commit_count = await self._query_commit_count(snapshot_date)
        snapshot.contributor_count = await self._query_contributor_count(snapshot_date)

    async def _run_cloc(self, path):
        proc = await asyncio.create_subprocess_exec(
            "cloc", path, "--json", "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return json.loads(stdout) if stdout else {}

    async def _run_lizard(self, path, language):
        proc = await asyncio.create_subprocess_exec(
            "lizard", path, "-l", language, "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return json.loads(stdout) if stdout else {"functions": []}

    async def _run_jscpd(self, path):
        proc = await asyncio.create_subprocess_exec(
            "npx", "jscpd", path, "--reporters", "json",
            "--min-lines", "10", "--min-tokens", "50", "--exit-code", "0",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        report_path = f"{path}/report/jscpd/jscpd-report.json"
        try:
            async with aiofiles.open(report_path) as f:
                return json.loads(await f.read())
        except FileNotFoundError:
            return {"statistics": {}, "duplicates": []}

    async def _run_ruff(self, path):
        proc = await asyncio.create_subprocess_exec(
            "ruff", "check", path, "--output-format", "json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        results = json.loads(stdout) if stdout else []
        errors = sum(1 for r in results if r.get("fix") is None)
        warnings = len(results) - errors
        return {"errors": errors, "warnings": warnings}

    async def _run_mypy(self, path):
        proc = await asyncio.create_subprocess_exec(
            "mypy", path, "--no-error-summary",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().split("\n") if stdout else []
        errors = sum(1 for l in lines if ": error:" in l)
        return {"errors": errors}

    async def _run_cppcheck(self, path):
        proc = await asyncio.create_subprocess_exec(
            "cppcheck", path, "--enable=warning,style", "--xml",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        # 解析 XML 输出统计 error/warning 数
        return {"errors": 0, "warnings": 0}  # 简化

    async def _run_grep_tech_debt(self, path):
        pattern = r"TODO|FIXME|HACK|XXX"
        proc = await asyncio.create_subprocess_exec(
            "grep", "-rn", "-E", pattern, path,
            "--include=*.py", "--include=*.cpp", "--include=*.h", "--include=*.hpp",
            "--include=*.sh", "--include=*.cmake",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().split("\n") if stdout else []
        return {"count": len(lines)}

    async def _run_grep_unsafe_functions(self, path):
        pattern = r"\b(memcpy|strcpy|strcat|sprintf|gets|scanf|strncpy|strncat|snprintf)\s*\("
        proc = await asyncio.create_subprocess_exec(
            "grep", "-rn", "-E", pattern, path,
            "--include=*.cpp", "--include=*.h", "--include=*.hpp", "--include=*.c",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().split("\n") if stdout else []
        items = []
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                items.append({"file": parts[0], "line": int(parts[1]) if parts[1].isdigit() else 0,
                              "function": "", "message": parts[2].strip()})
        return {"count": len(items), "items": items}

    async def _run_grep_warning_suppression(self, path):
        pattern = r"#pragma\s+(warning|GCC\s+diagnostic)"
        proc = await asyncio.create_subprocess_exec(
            "grep", "-rn", "-E", pattern, path,
            "--include=*.cpp", "--include=*.h", "--include=*.hpp", "--include=*.c",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        lines = stdout.decode().strip().split("\n") if stdout else []
        return {"count": len(lines)}
```

### 4.3 FileHeatmapUpdater

```python
class FileHeatmapUpdater:
    """从已有 Commit/PR 数据聚合文件变更热力图"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_store = DailyDataFileStore()

    async def update(self, repo: str):
        now = datetime.now(UTC)
        for days in [7, 30, 90]:
            start_date = (now - timedelta(days=days)).date()
            commit_data = await self._load_commit_data(repo, start_date)

            file_stats = defaultdict(lambda: {
                "change_count": 0, "additions": 0, "deletions": 0,
                "bug_fix_count": 0, "contributors": set(),
            })

            for date_str, data in commit_data.items():
                for commit in data.get("commits", []):
                    for file_path in commit.get("files_changed", []):
                        stats = file_stats[file_path]
                        stats["change_count"] += 1
                        stats["additions"] += commit.get("additions", 0)
                        stats["deletions"] += commit.get("deletions", 0)
                        stats["contributors"].add(commit.get("author", ""))

            for file_path, stats in file_stats.items():
                await self._upsert_heatmap(repo, file_path, stats, days)
```

### 4.4 版本对比采集策略

支持按 tag 对比（如 v0.13.0 vs v0.18.0）：
1. 采集时指定 `ref_type="tag"`, `ref_value="v0.13.0"`
2. CodeMetricsCollector 调用 `git checkout tags/v0.13.0`
3. 在该 tag 的代码快照上执行全量采集
4. 对比 API 通过两个日期/tag 的快照计算 delta

## 第五章 API 设计

### 5.1 API 端点总览

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | /api/v1/code-metrics/snapshots | 获取度量快照列表（分页） | user |
| GET | /api/v1/code-metrics/snapshots/latest | 获取最新快照 | user |
| GET | /api/v1/code-metrics/snapshots/{date} | 获取指定日期快照 | user |
| GET | /api/v1/code-metrics/trend | 获取指标趋势 | user |
| GET | /api/v1/code-metrics/compare | 两个日期/tag 的度量对比 | user |
| GET | /api/v1/code-metrics/complexity-details | 超大复杂度函数列表 | user |
| GET | /api/v1/code-metrics/duplication-details | 重复代码明细 | user |
| GET | /api/v1/code-metrics/security-details | C++ 安全问题明细 | user |
| GET | /api/v1/code-metrics/file-heatmap | 文件变更热力图 | user |
| GET | /api/v1/code-metrics/file-heatmap/top | Top N 热点文件 | user |
| GET | /api/v1/code-metrics/health-score | 健康度评分及趋势 | user |
| POST | /api/v1/code-metrics/collect | 手动触发采集 | super_admin |

### 5.2 Pydantic Schema 定义

```python
class CodeMetricsSnapshotResponse(BaseModel):
    id: int
    snapshot_date: date
    repo: str
    branch: str
    commit_sha: str | None
    ref_type: str
    ref_value: str
    total_loc: int | None
    total_raw_lines: int | None
    loc_python: int | None
    loc_cpp: int | None
    loc_cmake: int | None
    loc_shell: int | None
    loc_vllm_ascend: int | None
    loc_csrc: int | None
    total_functions: int | None
    total_files: int | None
    cc_total: int | None
    cc_per_method: float | None
    cc_maximum: int | None
    cc_huge_count: int | None
    cc_huge_ratio: float | None
    cc_adequacy: float | None
    max_depth: int | None
    depth_huge_count: int | None
    method_lines_total: int | None
    lines_per_method: float | None
    huge_method_count: int | None
    huge_method_ratio: float | None
    huge_file_count: int | None
    huge_headerfile_count: int | None
    dup_blocks: int | None
    dup_lines: int | None
    dup_ratio: float | None
    dup_files: int | None
    todo_count: int | None
    todo_kloc: float | None
    type_check_errors: int | None
    lint_errors: int | None
    lint_warnings: int | None
    unsafe_functions_count: int | None
    unsafe_functions_kloc: float | None
    warning_suppression_count: int | None
    warning_suppression_kloc: float | None
    pr_count: int | None
    pr_avg_size: float | None
    code_churn: int | None
    commit_count: int | None
    contributor_count: int | None
    health_score: float | None
    health_grade: str | None
    collection_status: str
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True

class MetricsTrendParams(BaseModel):
    metric: str  # cc_per_method / dup_ratio / health_score / total_loc / ...
    start_date: date
    end_date: date
    repo: str = "vllm-ascend"
    branch: str = "main"

class MetricsCompareResponse(BaseModel):
    date1: str
    date2: str
    metrics: dict[str, dict]  # {"total_loc": {"value1": 15000, "value2": 16200, "delta": 1200, "delta_pct": 8.0}}
    improved: list[str]
    degraded: list[str]

class ComplexityDetailResponse(BaseModel):
    id: int
    file_path: str
    function_name: str
    start_line: int | None
    language: str | None
    cyclomatic_complexity: int | None
    nesting_depth: int | None
    function_lines: int | None
    is_huge_cc: bool
    is_huge_depth: bool
    is_huge_method: bool

    class Config:
        from_attributes = True

class SecurityDetailResponse(BaseModel):
    id: int
    file_path: str
    line_number: int | None
    issue_type: str
    severity: str | None
    message: str | None
    function_name: str | None
    tool: str | None

    class Config:
        from_attributes = True

class CollectRequest(BaseModel):
    snapshot_date: date | None = None  # 默认昨天
    ref_type: str = "branch"  # branch/tag/commit
    ref_value: str = "main"
```

## 第六章 前端看板设计

### 6.1 页面布局（5 Tab）

Tab 1 总览：健康度雷达图（六维）+ 核心指标卡片 + 语言分布饼图 + 模块分布饼图 + 需关注项列表
Tab 2 复杂度：复杂度分布直方图 + 超大复杂度函数列表 + 超大函数列表
Tab 3 重复率：重复率概览 + 重复代码明细表
Tab 4 热力图：Top 20 热点文件 + 模块级热力图
Tab 5 趋势对比：指标选择器 + 趋势折线图 + 版本间对比表

### 6.2 组件清单

| 组件 | 类型 | 说明 |
|------|------|------|
| CodeMetricsBoard.tsx | Page | 主页面，含 5 Tab |
| HealthRadar.tsx | Chart | 健康度雷达图（Recharts RadarChart） |
| MetricsCard.tsx | Card | 核心指标卡片 |
| LanguagePie.tsx | Chart | 语言分布饼图 |
| ModulePie.tsx | Chart | 模块分布饼图 |
| ComplexityHistogram.tsx | Chart | 复杂度分布直方图 |
| ComplexityTable.tsx | Table | 超大函数列表 |
| DuplicationTable.tsx | Table | 重复代码明细 |
| SecurityTable.tsx | Table | C++ 安全问题列表 |
| FileHeatmap.tsx | Table | 文件热力图 |
| TrendChart.tsx | Chart | 趋势折线图 |
| VersionCompare.tsx | Table | 版本对比表 |

### 6.3 Hooks 设计

```typescript
// useCodeMetrics.ts
export const useCodeMetricsSnapshot = (date?: string) => {
  return useQuery({
    queryKey: ['code-metrics', 'snapshot', date],
    queryFn: () => codeMetricsService.getSnapshot(date),
  });
};

export const useCodeMetricsTrend = (params: MetricsTrendParams) => {
  return useQuery({
    queryKey: ['code-metrics', 'trend', params],
    queryFn: () => codeMetricsService.getTrend(params),
  });
};

export const useCodeMetricsCompare = (date1: string, date2: string) => {
  return useQuery({
    queryKey: ['code-metrics', 'compare', date1, date2],
    queryFn: () => codeMetricsService.compare(date1, date2),
  });
};

export const useComplexityDetails = (snapshotId: number) => {
  return useQuery({
    queryKey: ['code-metrics', 'complexity', snapshotId],
    queryFn: () => codeMetricsService.getComplexityDetails(snapshotId),
  });
};

export const useCollectCodeMetrics = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (req: CollectRequest) => codeMetricsService.collect(req),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['code-metrics'] }),
  });
};
```

## 第七章 调度器集成

### 7.1 新增定时任务

在 `backend/app/services/scheduler.py` 的 `start()` 方法中新增：

```python
from apscheduler.triggers.cron import CronTrigger

# 每日 06:30 采集代码度量
self.scheduler.add_job(
    self._collect_code_metrics_job,
    trigger=CronTrigger(hour=6, minute=30, timezone=self._timezone),
    id="code_metrics_collect",
    name="Collect Code Metrics (Cmetrics)",
    replace_existing=True,
)

# 每日 07:00 更新文件热力图
self.scheduler.add_job(
    self._update_file_heatmap_job,
    trigger=CronTrigger(hour=7, minute=0, timezone=self._timezone),
    id="file_heatmap_update",
    name="Update File Change Heatmap",
    replace_existing=True,
)
```

### 7.2 采集任务实现

```python
async def _collect_code_metrics_job(self):
    """每日代码度量采集"""
    async with SessionLocal() as db:
        yesterday = date.today() - timedelta(days=1)

        # 幂等检查
        existing = await db.execute(
            select(CodeMetricsSnapshot).where(
                CodeMetricsSnapshot.snapshot_date == yesterday,
                CodeMetricsSnapshot.repo == "vllm-ascend",
                CodeMetricsSnapshot.ref_value == "main",
            )
        )
        if existing.scalar_one_or_none():
            logger.info(f"Code metrics snapshot for {yesterday} already exists")
            return

        collector = CodeMetricsCollector(db, "vllm-ascend")
        await collector.collect(yesterday, ref_type="branch", ref_value="main")
        logger.info(f"Code metrics collected for {yesterday}")

async def _update_file_heatmap_job(self):
    """每日文件热力图更新"""
    async with SessionLocal() as db:
        updater = FileHeatmapUpdater(db)
        await updater.update("vllm-ascend")
        logger.info("File heatmap updated")
```

## 第八章 与 Cmetrics 指标映射

| Cmetrics 指标 | 本方案对应 | 采集工具 | 适配说明 |
|--------------|-----------|----------|----------|
| code_size | total_loc | cloc | 直接对应 |
| raw_lines | total_raw_lines | cloc | 直接对应 |
| methods_total | total_functions | lizard | 直接对应 |
| cyclomatic_complexity_total | cc_total | lizard | 直接对应 |
| cyclomatic_complexity_per_method | cc_per_method | 计算 | 直接对应 |
| maximum_cyclomatic_complexity | cc_maximum | lizard | 直接对应 |
| huge_cyclomatic_complexity_total | cc_huge_count | lizard | 阈值：Python 15, C++ 20 |
| huge_cyclomatic_complexity_ratio | cc_huge_ratio | 计算 | 直接对应 |
| cyclomatic_complexity_adequacy | cc_adequacy | 计算 | 直接对应 |
| maximum_depth | max_depth | lizard | 直接对应 |
| huge_depth_total | depth_huge_count | lizard | 阈值：5 |
| method_lines | method_lines_total | lizard | 直接对应 |
| lines_per_method | lines_per_method | 计算 | 直接对应 |
| huge_method_total | huge_method_count | lizard | 阈值：80 行 |
| huge_method_ratio | huge_method_ratio | 计算 | 直接对应 |
| files_total | total_files | cloc | 直接对应 |
| huge_non_headerfile_total | huge_file_count | cloc | 阈值：500 行 |
| huge_headerfile_total | huge_headerfile_count | cloc | C++ 专用，csrc/ 启用 |
| code_duplication_total | dup_blocks | jscpd | 直接对应 |
| code_duplication_ratio | dup_ratio | 计算 | 直接对应 |
| unsafe_functions_total | unsafe_functions_count | grep+cppcheck | C++ 专用，csrc/ 启用 |
| unsafe_functions_kloc | unsafe_functions_kloc | 计算 | C++ 专用 |
| redundant_code_total | todo_count | grep | Cmetrics 统计冗余代码，本方案统计 TODO/FIXME |
| redundant_code_kloc | todo_kloc | 计算 | 直接对应 |
| warning_suppression_total | warning_suppression_count | grep | C++ 专用，csrc/ 启用 |
| warning_suppression_kloc | warning_suppression_kloc | 计算 | C++ 专用 |

## 第九章 数据库迁移脚本

```python
"""升级到 v0.0.17: 代码度量看板"""

def upgrade():
    op.create_table('code_metrics_snapshots',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('snapshot_date', sa.Date, nullable=False, index=True),
        sa.Column('repo', sa.String(100), nullable=False),
        sa.Column('branch', sa.String(100), default='main'),
        sa.Column('commit_sha', sa.String(40)),
        sa.Column('ref_type', sa.String(20), default='branch'),
        sa.Column('ref_value', sa.String(100)),
        sa.Column('total_loc', sa.Integer), sa.Column('total_raw_lines', sa.Integer),
        sa.Column('loc_python', sa.Integer), sa.Column('loc_cpp', sa.Integer),
        sa.Column('loc_c', sa.Integer), sa.Column('loc_cmake', sa.Integer),
        sa.Column('loc_shell', sa.Integer),
        sa.Column('loc_vllm_ascend', sa.Integer), sa.Column('loc_csrc', sa.Integer),
        sa.Column('loc_tests', sa.Integer), sa.Column('loc_benchmarks', sa.Integer),
        sa.Column('loc_tools', sa.Integer), sa.Column('loc_docs', sa.Integer),
        sa.Column('total_functions', sa.Integer), sa.Column('total_files', sa.Integer),
        sa.Column('cc_total', sa.Integer), sa.Column('cc_per_method', sa.Float),
        sa.Column('cc_maximum', sa.Integer), sa.Column('cc_huge_count', sa.Integer),
        sa.Column('cc_huge_ratio', sa.Float), sa.Column('cc_adequacy', sa.Float),
        sa.Column('max_depth', sa.Integer), sa.Column('depth_huge_count', sa.Integer),
        sa.Column('depth_huge_ratio', sa.Float),
        sa.Column('method_lines_total', sa.Integer), sa.Column('lines_per_method', sa.Float),
        sa.Column('huge_method_count', sa.Integer), sa.Column('huge_method_ratio', sa.Float),
        sa.Column('huge_file_count', sa.Integer), sa.Column('huge_headerfile_count', sa.Integer),
        sa.Column('dup_blocks', sa.Integer), sa.Column('dup_lines', sa.Integer),
        sa.Column('dup_ratio', sa.Float), sa.Column('dup_files', sa.Integer),
        sa.Column('todo_count', sa.Integer), sa.Column('todo_kloc', sa.Float),
        sa.Column('type_check_errors', sa.Integer), sa.Column('lint_errors', sa.Integer),
        sa.Column('lint_warnings', sa.Integer),
        sa.Column('unsafe_functions_count', sa.Integer), sa.Column('unsafe_functions_kloc', sa.Float),
        sa.Column('warning_suppression_count', sa.Integer), sa.Column('warning_suppression_kloc', sa.Float),
        sa.Column('pr_count', sa.Integer), sa.Column('pr_avg_size', sa.Float),
        sa.Column('code_churn', sa.Integer), sa.Column('commit_count', sa.Integer),
        sa.Column('contributor_count', sa.Integer),
        sa.Column('health_score', sa.Float), sa.Column('health_grade', sa.String(5)),
        sa.Column('collection_duration', sa.Float), sa.Column('collection_status', sa.String(20)),
        sa.Column('error_message', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.now()),
        sa.UniqueConstraint('snapshot_date', 'repo', 'branch', 'ref_value', name='uq_metrics_snapshot'),
    )

    op.create_table('code_complexity_details',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('snapshot_id', sa.Integer, sa.ForeignKey('code_metrics_snapshots.id'), index=True),
        sa.Column('repo', sa.String(100), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('function_name', sa.String(200), nullable=False),
        sa.Column('start_line', sa.Integer), sa.Column('language', sa.String(20)),
        sa.Column('cyclomatic_complexity', sa.Integer), sa.Column('nesting_depth', sa.Integer),
        sa.Column('function_lines', sa.Integer), sa.Column('parameter_count', sa.Integer),
        sa.Column('is_huge_cc', sa.Boolean, default=False),
        sa.Column('is_huge_depth', sa.Boolean, default=False),
        sa.Column('is_huge_method', sa.Boolean, default=False),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.now()),
    )

    op.create_table('code_duplication_details',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('snapshot_id', sa.Integer, sa.ForeignKey('code_metrics_snapshots.id'), index=True),
        sa.Column('source_file', sa.String(500), nullable=False),
        sa.Column('source_start_line', sa.Integer),
        sa.Column('target_file', sa.String(500), nullable=False),
        sa.Column('target_start_line', sa.Integer),
        sa.Column('duplicate_lines', sa.Integer), sa.Column('code_fragment', sa.Text),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.now()),
    )

    op.create_table('file_change_heatmap',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('repo', sa.String(100), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('change_count_7d', sa.Integer, default=0),
        sa.Column('change_count_30d', sa.Integer, default=0),
        sa.Column('change_count_90d', sa.Integer, default=0),
        sa.Column('additions_30d', sa.Integer, default=0),
        sa.Column('deletions_30d', sa.Integer, default=0),
        sa.Column('bug_fix_count_30d', sa.Integer, default=0),
        sa.Column('contributors_30d', sa.JSON),
        sa.Column('last_changed_at', sa.TIMESTAMP),
        sa.Column('updated_at', sa.TIMESTAMP, server_default=sa.func.now()),
        sa.UniqueConstraint('repo', 'file_path', name='uq_file_heatmap'),
    )

    op.create_table('code_security_details',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('snapshot_id', sa.Integer, sa.ForeignKey('code_metrics_snapshots.id'), index=True),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('line_number', sa.Integer),
        sa.Column('issue_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20)),
        sa.Column('message', sa.String(500)),
        sa.Column('function_name', sa.String(200)),
        sa.Column('tool', sa.String(50)),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.now()),
    )

def downgrade():
    op.drop_table('code_security_details')
    op.drop_table('file_change_heatmap')
    op.drop_table('code_duplication_details')
    op.drop_table('code_complexity_details')
    op.drop_table('code_metrics_snapshots')
```

## 第十章 实施路径

| 阶段 | 内容 | 依赖 | 工作量 |
|------|------|------|--------|
| P1 | 采集工具链安装验证（cloc/lizard/jscpd/ruff/mypy/cppcheck/clang-tidy） | 无 | 1天 |
| P2 | 数据模型（5张表）+ 迁移脚本 | P1 | 1天 |
| P3 | 采集服务（CodeMetricsCollector + FileHeatmapUpdater） | P1+P2 | 3天 |
| P4 | 调度集成（2个定时任务） | P3 | 0.5天 |
| P5 | API 层（12端点 + Schema） | P2 | 2天 |
| P6 | 前端看板（5 Tab + 组件 + hooks） | P5 | 4天 |
| P7 | 告警集成（健康度降级告警） | P6 | 1天 |

## 第十一章 与现有模块的关系

| 现有模块 | 变化类型 | 说明 |
|----------|----------|------|
| GitHubLocalCache | 复用 | 获取本地仓库路径，git checkout 切换版本 |
| PullRequest | 读取 | 聚合 PR 级代码变更量 |
| DailyDataFileStore | 读取 | 聚合 Commit 级文件变更频率 |
| CommitAnalysisFileStore | 读取 | 聚合修改类型分布、闭环率 |
| CIResult / CIJob | 读取 | 关联 CI 通过率与代码度量 |
| AlertRule | 扩展(P7) | 新增代码度量告警规则类型 |
| DataSyncScheduler | 扩展 | 新增 2 个定时任务 |
| main.py | 扩展 | 注册 code_metrics 路由 |
| models/__init__.py | 扩展 | 新增 5 个模型类 |
| 新增 code_metrics.py (service) | 全新 | 采集服务 + 查询服务 |
| 新增 code_metrics.py (api) | 全新 | 12 个 API 端点 |
| 新增 CodeMetricsBoard.tsx | 全新 | 前端看板页面 |
