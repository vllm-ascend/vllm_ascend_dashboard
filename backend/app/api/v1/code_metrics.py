"""代码度量看板 API"""
import logging
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import select, func, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.api.deps import CurrentUser, DbSession
from app.models import (
    CodeMetricsSnapshot, CodeComplexityDetail, CodeDuplicationDetail,
    CodeSecurityDetail, CodeMetricsFileHeatmap
)

router = APIRouter()
logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


@router.post("/snapshot", summary="上传代码度量快照（CI 调用）")
async def upload_snapshot(
    body: dict,
    current_user: CurrentUser,
    db: DbSession,
):
    """接收 CI 上传的代码度量快照数据"""
    snapshot_date = body.get("snapshot_date")
    if not snapshot_date:
        snapshot_date = date.today().isoformat()
    
    repo = body.get("repo", "vllm-ascend")
    branch = body.get("branch", "main")
    
    # 幂等：同日期同repo同branch先删旧数据
    old = await db.execute(
        select(CodeMetricsSnapshot).where(
            CodeMetricsSnapshot.snapshot_date == snapshot_date,
            CodeMetricsSnapshot.repo == repo,
            CodeMetricsSnapshot.branch == branch,
        )
    )
    for old_snap in old.scalars().all():
        await db.delete(old_snap)
    await db.flush()
    
    # 创建快照
    snapshot = CodeMetricsSnapshot(
        repo=repo,
        branch=branch,
        snapshot_date=snapshot_date,
        collection_status=body.get("collection_status", "complete"),
        collection_duration_seconds=body.get("collection_duration_seconds", 0),
        total_loc=body.get("total_loc", 0),
        total_raw_lines=body.get("total_raw_lines", 0),
        loc_python=body.get("loc_python", 0),
        loc_cpp=body.get("loc_cpp", 0),
        loc_c=body.get("loc_c", 0),
        loc_cmake=body.get("loc_cmake", 0),
        loc_shell=body.get("loc_shell", 0),
        total_functions=body.get("total_functions", 0),
        total_files=body.get("total_files", 0),
        cc_total=body.get("cc_total", 0),
        cc_per_method=body.get("cc_per_method", 0),
        cc_maximum=body.get("cc_maximum", 0),
        cc_huge_count=body.get("cc_huge_count", 0),
        cc_huge_ratio=body.get("cc_huge_ratio", 0),
        cc_adequacy=body.get("cc_adequacy", 0),
        max_depth=body.get("max_depth", 0),
        depth_huge_count=body.get("depth_huge_count", 0),
        depth_huge_ratio=body.get("depth_huge_ratio", 0),
        method_lines_total=body.get("method_lines_total", 0),
        lines_per_method=body.get("lines_per_method", 0),
        huge_method_count=body.get("huge_method_count", 0),
        huge_method_ratio=body.get("huge_method_ratio", 0),
        huge_file_count=body.get("huge_file_count", 0),
        huge_headerfile_count=body.get("huge_headerfile_count", 0),
        dup_blocks=body.get("dup_blocks", 0),
        dup_lines=body.get("dup_lines", 0),
        dup_ratio=body.get("dup_ratio", 0),
        unsafe_functions_count=body.get("unsafe_functions_count", 0),
        warning_suppression_count=body.get("warning_suppression_count", 0),
        lint_errors=body.get("lint_errors", 0),
        lint_warnings=body.get("lint_warnings", 0),
        todo_count=body.get("todo_count", 0),
        fixme_count=body.get("fixme_count", 0),
        hack_count=body.get("hack_count", 0),
        health_score=body.get("health_score", 0),
        health_score_complexity=body.get("health_score_complexity", 0),
        health_score_security=body.get("health_score_security", 0),
        health_score_duplication=body.get("health_score_duplication", 0),
        health_score_method_size=body.get("health_score_method_size", 0),
        health_score_tech_debt=body.get("health_score_tech_debt", 0),
        health_score_lint=body.get("health_score_lint", 0),
        module_loc=body.get("module_loc"),
        language_loc=body.get("language_loc"),
    )
    db.add(snapshot)
    await db.flush()
    
    # 存储复杂度明细
    for item in body.get("complexity_details", [])[:500]:
        db.add(CodeComplexityDetail(
            snapshot_id=snapshot.id,
            file_path=item.get("file_path", ""),
            function_name=item.get("function_name", ""),
            language=item.get("language"),
            cyclomatic_complexity=item.get("cyclomatic_complexity"),
            max_nesting_depth=item.get("max_nesting_depth"),
            function_lines=item.get("function_lines"),
            start_line=item.get("start_line"),
        ))
    
    # 存储重复率明细
    for item in body.get("duplication_details", [])[:200]:
        db.add(CodeDuplicationDetail(
            snapshot_id=snapshot.id,
            file_a=item.get("file_a", ""),
            file_b=item.get("file_b", ""),
            lines=item.get("lines", 0),
            token_count=item.get("token_count", 0),
            fragment=item.get("fragment"),
        ))
    
    # 存储安全规范明细
    for item in body.get("security_details", [])[:500]:
        db.add(CodeSecurityDetail(
            snapshot_id=snapshot.id,
            file_path=item.get("file_path", ""),
            line_number=item.get("line_number"),
            severity=item.get("severity"),
            tool=item.get("tool"),
            rule_id=item.get("rule_id"),
            message=item.get("message"),
        ))
    
    await db.commit()
    return {"id": snapshot.id, "status": "saved", "snapshot_date": snapshot_date}


@router.get("/overview", summary="总览数据")
async def get_overview(
    current_user: CurrentUser,
    db: DbSession,
    days: int = Query(30, ge=1, le=365),
):
    """获取代码度量总览数据（最新快照）"""
    stmt = select(CodeMetricsSnapshot).order_by(
        CodeMetricsSnapshot.snapshot_date.desc()
    ).limit(1)
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()
    
    if not snapshot:
        return {"has_data": False, "message": "暂无代码度量数据"}
    
    return {
        "has_data": True,
        "snapshot_date": snapshot.snapshot_date.isoformat() if snapshot.snapshot_date else None,
        "collection_status": snapshot.collection_status,
        "health_score": snapshot.health_score,
        "health_scores": {
            "complexity": snapshot.health_score_complexity,
            "security": snapshot.health_score_security,
            "duplication": snapshot.health_score_duplication,
            "method_size": snapshot.health_score_method_size,
            "tech_debt": snapshot.health_score_tech_debt,
            "lint": snapshot.health_score_lint,
        },
        "metrics": {
            "total_loc": snapshot.total_loc,
            "total_functions": snapshot.total_functions,
            "total_files": snapshot.total_files,
            "cc_per_method": snapshot.cc_per_method,
            "cc_maximum": snapshot.cc_maximum,
            "cc_huge_count": snapshot.cc_huge_count,
            "dup_ratio": snapshot.dup_ratio,
            "dup_blocks": snapshot.dup_blocks,
            "unsafe_functions_count": snapshot.unsafe_functions_count,
            "lint_errors": snapshot.lint_errors,
            "todo_count": snapshot.todo_count,
            "fixme_count": snapshot.fixme_count,
        },
        "language_loc": snapshot.language_loc or {},
        "module_loc": snapshot.module_loc or {},
    }


@router.get("/complexity", summary="复杂度详情")
async def get_complexity(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(50, ge=1, le=500),
):
    """获取最新快照的复杂度明细"""
    latest = await db.execute(
        select(CodeMetricsSnapshot.id).order_by(
            CodeMetricsSnapshot.snapshot_date.desc()
        ).limit(1)
    )
    snapshot_id = latest.scalar_one_or_none()
    if not snapshot_id:
        return {"items": []}
    
    stmt = (
        select(CodeComplexityDetail)
        .where(CodeComplexityDetail.snapshot_id == snapshot_id)
        .order_by(CodeComplexityDetail.cyclomatic_complexity.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return {
        "items": [
            {
                "file_path": r.file_path,
                "function_name": r.function_name,
                "language": r.language,
                "cyclomatic_complexity": r.cyclomatic_complexity,
                "max_nesting_depth": r.max_nesting_depth,
                "function_lines": r.function_lines,
            }
            for r in result.scalars().all()
        ]
    }


@router.get("/duplication", summary="重复率详情")
async def get_duplication(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
):
    """获取最新快照的重复代码块明细"""
    latest = await db.execute(
        select(CodeMetricsSnapshot.id).order_by(
            CodeMetricsSnapshot.snapshot_date.desc()
        ).limit(1)
    )
    snapshot_id = latest.scalar_one_or_none()
    if not snapshot_id:
        return {"items": []}
    
    stmt = (
        select(CodeDuplicationDetail)
        .where(CodeDuplicationDetail.snapshot_id == snapshot_id)
        .order_by(CodeDuplicationDetail.lines.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return {
        "items": [
            {
                "file_a": r.file_a,
                "file_b": r.file_b,
                "lines": r.lines,
                "fragment": r.fragment[:200] if r.fragment else None,
            }
            for r in result.scalars().all()
        ]
    }


@router.get("/heatmap", summary="文件热力图")
async def get_heatmap(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=100),
):
    """获取文件变更热力图 Top N"""
    stmt = (
        select(CodeMetricsFileHeatmap)
        .order_by(CodeMetricsFileHeatmap.change_count.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return {
        "items": [
            {
                "file_path": r.file_path,
                "change_count": r.change_count,
                "bug_fix_count": r.bug_fix_count,
                "last_changed": r.last_changed.isoformat() if r.last_changed else None,
            }
            for r in result.scalars().all()
        ]
    }


@router.get("/trends", summary="趋势数据")
async def get_trends(
    current_user: CurrentUser,
    db: DbSession,
    days: int = Query(30, ge=1, le=365),
):
    """获取代码度量趋势数据"""
    cutoff = date.today() - timedelta(days=days)
    stmt = (
        select(CodeMetricsSnapshot)
        .where(CodeMetricsSnapshot.snapshot_date >= cutoff)
        .order_by(CodeMetricsSnapshot.snapshot_date.asc())
    )
    result = await db.execute(stmt)
    snapshots = result.scalars().all()
    return {
        "items": [
            {
                "date": s.snapshot_date.isoformat() if s.snapshot_date else None,
                "total_loc": s.total_loc,
                "total_functions": s.total_functions,
                "cc_per_method": s.cc_per_method,
                "cc_huge_count": s.cc_huge_count,
                "dup_ratio": s.dup_ratio,
                "health_score": s.health_score,
                "lint_errors": s.lint_errors,
                "todo_count": s.todo_count + s.fixme_count + s.hack_count,
            }
            for s in snapshots
        ]
    }


@router.post("/cleanup", summary="清理过期明细数据（管理员）")
async def cleanup_old_details(
    current_user: CurrentUser,
    db: DbSession,
    retention_days: int = Query(365, ge=30, le=3650),
):
    """清理超过保留期限的明细数据"""
    cutoff_date = date.today() - timedelta(days=retention_days)
    
    # 找到过期快照 ID
    old_snapshots = await db.execute(
        select(CodeMetricsSnapshot.id).where(
            CodeMetricsSnapshot.snapshot_date < cutoff_date
        )
    )
    old_ids = [row[0] for row in old_snapshots]
    
    if not old_ids:
        return {"deleted": 0, "message": "No expired data found"}
    
    # 删除关联明细
    await db.execute(
        delete(CodeComplexityDetail).where(CodeComplexityDetail.snapshot_id.in_(old_ids))
    )
    await db.execute(
        delete(CodeDuplicationDetail).where(CodeDuplicationDetail.snapshot_id.in_(old_ids))
    )
    await db.execute(
        delete(CodeSecurityDetail).where(CodeSecurityDetail.snapshot_id.in_(old_ids))
    )
    # 删除快照本身
    await db.execute(
        delete(CodeMetricsSnapshot).where(CodeMetricsSnapshot.id.in_(old_ids))
    )
    await db.commit()
    
    return {"deleted": len(old_ids), "retention_days": retention_days}
