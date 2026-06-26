"""
CI 数据 API 路由
Phase 2: 实现数据采集和展示
"""
import json
import logging
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import CurrentSuperAdminUser, DbSession, CurrentAdminUser
from app.core.config import settings
from app.models import CIJob, CIResult, JobOwner, User, WorkflowConfig, JobFailureAnalysis
from app.schemas import (
    CIDailyReport,
    CIJobDetailResponse,
    CIJobResponse,
    CIResultResponse,
    CIStats,
    CISyncResponse,
    CITrend,
    WorkflowLatestResult,
    FailureAnalysisResponse,
    FailureAnalysisListResponse,
)
from app.services.scheduler import get_scheduler
from app.services.sync_progress import get_sync_progress

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/workflows", response_model=list[str])
async def list_workflows(
    db: DbSession
):
    """获取 workflow 列表"""
    stmt = select(CIResult.workflow_name).distinct()
    result = await db.execute(stmt)
    workflows = result.all()
    return [w[0] for w in workflows]


@router.get("/runs", response_model=list[CIResultResponse])
async def list_runs(
    db: DbSession,
    workflow_name: str | None = None,
    status: str | None = None,
    hardware: str | None = None,
    limit: int = Query(100, ge=1, le=500)
):
    """获取 CI 运行列表（只返回启用的 workflow 的运行记录）"""
    # 获取启用的 workflow 名称列表
    enabled_stmt = select(WorkflowConfig.workflow_name).where(WorkflowConfig.enabled == True)
    enabled_result = await db.execute(enabled_stmt)
    enabled_workflows = [row[0] for row in enabled_result.all()]

    # 如果没有启用的 workflow，直接返回空列表
    if not enabled_workflows:
        return []

    stmt = select(CIResult).where(CIResult.workflow_name.in_(enabled_workflows))

    if workflow_name:
        stmt = stmt.where(CIResult.workflow_name == workflow_name)
    if status:
        stmt = stmt.where(CIResult.status == status)
    if hardware:
        stmt = stmt.where(CIResult.hardware == hardware)

    stmt = stmt.order_by(
        CIResult.started_at.desc()
    ).limit(limit)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/workflows/latest", response_model=list[WorkflowLatestResult])
async def get_workflows_latest_results(
    db: DbSession,
    workflow_name: str | None = None,
    hardware: str | None = None
):
    """获取每个 workflow 最近一次的 job 结果（只返回启用的 workflow）"""
    # 获取启用的 workflow 名称列表
    enabled_stmt = select(WorkflowConfig.workflow_name, WorkflowConfig.hardware).where(WorkflowConfig.enabled == True)
    if workflow_name:
        enabled_stmt = enabled_stmt.where(WorkflowConfig.workflow_name == workflow_name)
    if hardware:
        enabled_stmt = enabled_stmt.where(WorkflowConfig.hardware == hardware)

    enabled_result = await db.execute(enabled_stmt)
    enabled_workflows = enabled_result.all()

    # 如果没有启用的 workflow，直接返回空列表
    if not enabled_workflows:
        return []

    results = []
    for wf_name, wf_hardware in enabled_workflows:
        # 获取每个 workflow 最近的运行记录（按 completed_at 降序，取最新的）
        stmt = select(CIResult).where(
            CIResult.workflow_name == wf_name
        ).order_by(
            CIResult.completed_at.desc()
        ).limit(1)

        result = await db.execute(stmt)
        latest_run = result.scalar_one_or_none()

        latest_run_data = None
        if latest_run:
            latest_run_data = {
                "run_id": latest_run.run_id,
                "status": latest_run.status,
                "conclusion": latest_run.conclusion,
                "started_at": latest_run.started_at.isoformat() if latest_run.started_at else None,
                "duration_seconds": latest_run.duration_seconds,
                "github_html_url": f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{latest_run.run_id}" if latest_run.run_id else None,
            }

        results.append(WorkflowLatestResult(
            workflow_name=wf_name,
            hardware=wf_hardware,
            latest_run=latest_run_data,
        ))

    return results


@router.get("/stats", response_model=CIStats)
async def get_ci_stats(
    db: DbSession,
    workflow_name: str | None = None,
    hardware: str | None = None
):
    """获取 CI 统计数据（只统计启用的 workflow）"""
    # 获取启用的 workflow 名称列表
    enabled_stmt = select(WorkflowConfig.workflow_name).where(WorkflowConfig.enabled == True)
    enabled_result = await db.execute(enabled_stmt)
    enabled_workflows = [row[0] for row in enabled_result.all()]

    # 构建基础查询（只查询启用的 workflow）
    base_query = select(CIResult).where(CIResult.workflow_name.in_(enabled_workflows))
    if workflow_name:
        base_query = base_query.where(CIResult.workflow_name == workflow_name)
    if hardware:
        base_query = base_query.where(CIResult.hardware == hardware)

    # 总运行次数
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_runs_result = await db.execute(count_stmt)
    total_runs = total_runs_result.scalar() or 0

    # 成功次数
    success_query = select(func.count()).select_from(
        select(CIResult)
        .where(CIResult.conclusion == "success")
        .where(CIResult.workflow_name.in_(enabled_workflows))
        .subquery()
    )
    if workflow_name:
        success_query = select(func.count()).select_from(
            select(CIResult)
            .where(CIResult.conclusion == "success")
            .where(CIResult.workflow_name == workflow_name)
            .where(CIResult.workflow_name.in_(enabled_workflows))
            .subquery()
        )
    if hardware:
        success_query = select(func.count()).select_from(
            select(CIResult)
            .where(CIResult.conclusion == "success")
            .where(CIResult.hardware == hardware)
            .where(CIResult.workflow_name.in_(enabled_workflows))
            .subquery()
        )
    success_runs_result = await db.execute(success_query)
    success_runs = success_runs_result.scalar() or 0

    # 成功率
    success_rate = (success_runs / total_runs * 100) if total_runs > 0 else 0.0

    # 平均时长
    avg_query = select(func.avg(CIResult.duration_seconds)).where(
        CIResult.duration_seconds.isnot(None)
    ).where(CIResult.workflow_name.in_(enabled_workflows))
    if workflow_name:
        avg_query = avg_query.where(CIResult.workflow_name == workflow_name)
    if hardware:
        avg_query = avg_query.where(CIResult.hardware == hardware)

    avg_result = await db.execute(avg_query)
    avg_duration = avg_result.scalar()
    avg_duration_seconds = float(avg_duration) if avg_duration else None

    # 最近 7 天统计（使用 completed_at 而不是 created_at）
    seven_days_ago = datetime.now(UTC) - timedelta(days=7)
    last_7_days_query = select(func.count()).select_from(
        select(CIResult)
        .where(CIResult.completed_at >= seven_days_ago)
        .where(CIResult.workflow_name.in_(enabled_workflows))
        .subquery()
    )
    if workflow_name:
        last_7_days_query = select(func.count()).select_from(
            select(CIResult)
            .where(CIResult.completed_at >= seven_days_ago)
            .where(CIResult.workflow_name == workflow_name)
            .where(CIResult.workflow_name.in_(enabled_workflows))
            .subquery()
        )
    if hardware:
        last_7_days_query = select(func.count()).select_from(
            select(CIResult)
            .where(CIResult.completed_at >= seven_days_ago)
            .where(CIResult.hardware == hardware)
            .where(CIResult.workflow_name.in_(enabled_workflows))
            .subquery()
        )

    last_7_days_result = await db.execute(last_7_days_query)
    last_7_days_runs = last_7_days_result.scalar() or 0

    # 最近 7 天成功率
    last_7_days_success_query = select(func.count()).select_from(
        select(CIResult)
        .where(CIResult.completed_at >= seven_days_ago)
        .where(CIResult.conclusion == "success")
        .where(CIResult.workflow_name.in_(enabled_workflows))
        .subquery()
    )
    if workflow_name:
        last_7_days_success_query = select(func.count()).select_from(
            select(CIResult)
            .where(CIResult.completed_at >= seven_days_ago)
            .where(CIResult.workflow_name == workflow_name)
            .where(CIResult.conclusion == "success")
            .subquery()
        )
    if hardware:
        last_7_days_success_query = select(func.count()).select_from(
            select(CIResult)
            .where(CIResult.completed_at >= seven_days_ago)
            .where(CIResult.hardware == hardware)
            .where(CIResult.conclusion == "success")
            .subquery()
        )

    last_7_days_success_result = await db.execute(last_7_days_success_query)
    last_7_days_success = last_7_days_success_result.scalar() or 0
    last_7_days_success_rate = (last_7_days_success / last_7_days_runs * 100) if last_7_days_runs > 0 else 0.0

    # 最近 7 天平均时长（使用 completed_at）
    last_7_days_avg_query = select(func.avg(CIResult.duration_seconds)).where(
        CIResult.completed_at >= seven_days_ago,
        CIResult.duration_seconds.isnot(None),
        CIResult.workflow_name.in_(enabled_workflows),
    )
    if workflow_name:
        last_7_days_avg_query = last_7_days_avg_query.where(CIResult.workflow_name == workflow_name)
    if hardware:
        last_7_days_avg_query = last_7_days_avg_query.where(CIResult.hardware == hardware)

    last_7_days_avg_result = await db.execute(last_7_days_avg_query)
    last_7_days_avg_duration = last_7_days_avg_result.scalar()
    last_7_days_avg_duration_seconds = float(last_7_days_avg_duration) if last_7_days_avg_duration else None

    return {
        "total_runs": total_runs,
        "success_rate": round(success_rate, 2),
        "avg_duration_seconds": avg_duration_seconds,
        "last_7_days": {
            "runs": last_7_days_runs,
            "success_rate": round(last_7_days_success_rate, 2),
            "avg_duration_seconds": last_7_days_avg_duration_seconds,
        }
    }


@router.get("/trends", response_model=list[CITrend])
async def get_ci_trends(
    db: DbSession,
    days: int = Query(7, ge=1, le=30, description="获取多少天的趋势数据"),
    workflow_name: str | None = None,
    hardware: str | None = None,
):
    """
    获取 CI 趋势数据（只统计启用的 workflow）

    按天统计运行次数、成功率等指标
    """
    # 计算起始时间
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days)

    # 获取启用的 workflow 名称列表
    enabled_stmt = select(WorkflowConfig.workflow_name).where(WorkflowConfig.enabled == True)
    enabled_result = await db.execute(enabled_stmt)
    enabled_workflows = [row[0] for row in enabled_result.all()]

    # 如果没有启用的 workflow，直接返回空列表
    if not enabled_workflows:
        return []

    # 构建基础查询
    stmt = select(
        cast(CIResult.created_at, Date).label('date'),
        func.count().label('total_runs'),
        func.sum(
            case(
                (CIResult.conclusion == "success", 1),
                else_=0
            )
        ).label('success_runs'),
        func.avg(
            case(
                (CIResult.duration_seconds.isnot(None), CIResult.duration_seconds),
                else_=None
            )
        ).label('avg_duration'),
    ).where(
        CIResult.created_at >= start_date,
        CIResult.created_at <= end_date,
        CIResult.workflow_name.in_(enabled_workflows),
    )

    if workflow_name:
        stmt = stmt.where(CIResult.workflow_name == workflow_name)
    if hardware:
        stmt = stmt.where(CIResult.hardware == hardware)

    stmt = stmt.group_by(
        cast(CIResult.created_at, Date)
    ).order_by(
        cast(CIResult.created_at, Date)
    )

    result = await db.execute(stmt)
    rows = result.all()

    # 转换为响应格式
    trends = []
    for row in rows:
        trends.append(CITrend(
            date=str(row.date),
            total_runs=row.total_runs,
            success_runs=row.success_runs,
            success_rate=round(row.success_runs / row.total_runs * 100, 2) if row.total_runs > 0 else 0.0,
            avg_duration_seconds=float(row.avg_duration) if row.avg_duration else None,
        ))

    return trends


@router.post("/sync", response_model=CISyncResponse)
async def trigger_sync(
    current_user: CurrentSuperAdminUser,
    days_back: int = Query(default=7, ge=1, le=90, description="从多少天前开始采集"),
    max_runs_per_workflow: int = Query(default=100, ge=1, le=1000, description="每个 workflow 最多采集多少条记录"),
    force_full_refresh: bool = Query(default=False, description="是否强制全量覆盖刷新"),
):
    """
    手动触发数据同步（异步执行，立即返回）

    需要超级管理员权限（super_admin）

    Args:
        days_back: 从多少天前开始采集（默认 7 天，最多 90 天）
        max_runs_per_workflow: 每个 workflow 最多采集多少条记录（默认 100，最多 1000）
        force_full_refresh: 是否强制全量覆盖刷新（默认 False，增量刷新）
    """
    try:
        # 重置并初始化进度跟踪器
        from app.services.sync_progress import get_sync_progress, reset_sync_progress
        reset_sync_progress()

        # 预先获取 workflow 数量并初始化进度
        from sqlalchemy import select

        from app.db.base import SessionLocal
        from app.models import WorkflowConfig
        
        # 使用 async with 正确管理异步会话
        async with SessionLocal() as db:
            stmt = select(WorkflowConfig).where(WorkflowConfig.enabled == True)
            result = await db.execute(stmt)
            workflow_configs = result.scalars().all()
            progress = get_sync_progress()
            progress.total_workflows = len(workflow_configs)
            progress.start()  # 开始同步状态

        # 在后台异步执行同步任务
        import asyncio
        async def run_sync():
            try:
                scheduler = get_scheduler()
                await scheduler.trigger_manual_sync(
                    sync_type="ci",
                    days_back=days_back,
                    max_runs_per_workflow=max_runs_per_workflow,
                    force_full_refresh=force_full_refresh,
                )
            except Exception as e:
                logger.error(f"Background sync failed: {e}")
                progress = get_sync_progress()
                progress.fail(str(e))

        # 启动后台任务（不等待）
        asyncio.create_task(run_sync())

        # 立即返回，让前端开始轮询进度
        return CISyncResponse(
            success=True,
            message="Sync started, check progress via /ci/sync/progress",
            collected_count=0,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        )


@router.get("/sync/status")
async def get_sync_status():
    """获取同步任务状态"""
    try:
        scheduler = get_scheduler()
        jobs = scheduler.get_job_info()

        return {
            "scheduler_running": scheduler.scheduler.running,
            "jobs": jobs,
        }
    except Exception as e:
        return {
            "scheduler_running": False,
            "error": str(e),
        }


@router.get("/sync/progress")
async def get_sync_progress_info():
    """获取同步进度详情"""
    try:
        progress = get_sync_progress()
        return progress.get_progress()
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e),
        }


@router.get("/debug/workflows")
async def debug_workflows():
    """
    调试接口：获取 GitHub 上实际的 workflow 列表
    
    用于排查 workflow 文件名不匹配问题
    """
    try:
        from app.core.config import settings
        from app.services.github_client import GitHubClient

        if not settings.GITHUB_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="GITHUB_TOKEN not configured",
            )

        client = GitHubClient(
            token=settings.GITHUB_TOKEN,
            owner=settings.GITHUB_OWNER,
            repo=settings.GITHUB_REPO,
        )

        try:
            # 获取所有 workflows
            url = f"/repos/{client.owner}/{client.repo}/actions/workflows"
            result = await client._request("GET", url)
            workflows = result.get("workflows", [])

            # 检查配置的 workflow 是否存在
            from app.services.ci_collector import CICollector
            configured_workflows = CICollector.WORKFLOW_FILES

            workflow_names = [w["path"].split("/")[-1] for w in workflows]

            return {
                "configured_workflows": configured_workflows,
                "github_workflows": workflow_names,
                "match_status": {
                    name: name in workflow_names
                    for name in configured_workflows
                },
                "total_workflows": len(workflows),
            }
        finally:
            await client.close()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Debug failed: {str(e)}",
        )


@router.get("/runs/{run_id}/jobs", response_model=list[CIJobResponse])
async def list_jobs_by_run(
    run_id: int,
    db: DbSession
):
    """获取指定 workflow run 的所有 jobs"""
    stmt = select(CIJob).where(CIJob.run_id == run_id).order_by(CIJob.id)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    response = []
    for job in jobs:
        # 解析 steps_summary 和 runner_labels
        steps_summary = []
        if job.steps_data:
            try:
                steps_summary = json.loads(job.steps_data)
            except Exception:
                pass

        runner_labels = []
        if job.runner_labels:
            try:
                runner_labels = json.loads(job.runner_labels)
            except Exception:
                pass

        response.append(CIJobResponse(
            id=job.id,
            job_id=job.job_id,
            run_id=job.run_id,
            workflow_name=job.workflow_name,
            job_name=job.job_name,
            status=job.status,
            conclusion=job.conclusion,
            hardware=job.hardware,
            runner_name=job.runner_name,
            started_at=job.started_at,
            completed_at=job.completed_at,
            duration_seconds=job.duration_seconds,
            runner_labels=runner_labels,
            steps_summary=steps_summary,
            created_at=job.created_at,
        ))

    return response


@router.get("/jobs/{job_id}", response_model=CIJobDetailResponse)
async def get_job_detail(
    job_id: int,
    db: DbSession
):
    """获取 job 详细信息"""
    stmt = select(CIJob).where(CIJob.job_id == job_id)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )

    # 解析数据
    steps_data = []
    if job.steps_data:
        try:
            steps_data = json.loads(job.steps_data)
        except Exception:
            pass

    runner_labels = []
    if job.runner_labels:
        try:
            runner_labels = json.loads(job.runner_labels)
        except Exception:
            pass

    return CIJobDetailResponse(
        id=job.id,
        job_id=job.job_id,
        run_id=job.run_id,
        workflow_name=job.workflow_name,
        job_name=job.job_name,
        status=job.status,
        conclusion=job.conclusion,
        hardware=job.hardware,
        runner_name=job.runner_name,
        started_at=job.started_at,
        completed_at=job.completed_at,
        duration_seconds=job.duration_seconds,
        runner_labels=runner_labels,
        steps_summary=steps_data,
        steps_data=steps_data,
        logs_url=job.logs_url,
        created_at=job.created_at,
    )


@router.get("/reports/daily/{date}", response_model=CIDailyReport)
async def get_daily_report(
    date: str,
    db: DbSession
):
    """
    获取指定日期的 CI 每日报告

    Args:
        date: 日期，格式 YYYY-MM-DD (北京时间)

    Returns:
        CIDailyReport: 包含统计数据、workflow 结果和 markdown 报告
    """
    try:
        # 解析日期 (北京时间)
        try:
            report_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD"
            )

        # 使用北京时间 (CST/UTC+8)
        from datetime import timezone as tz
        beijing_tz = tz(timedelta(hours=8))

        # 获取当天的起始和结束时间 (北京时间)
        start_datetime = datetime.combine(report_date, datetime.min.time()).replace(tzinfo=beijing_tz)
        end_datetime = start_datetime + timedelta(days=1)

        # 转换为 UTC 时间用于数据库查询 (数据库存储的是 UTC)
        start_datetime_utc = start_datetime.astimezone(UTC)
        end_datetime_utc = end_datetime.astimezone(UTC)

        # 获取启用的 workflow 名称列表
        enabled_stmt = select(WorkflowConfig.workflow_name).where(WorkflowConfig.enabled == True)
        enabled_result = await db.execute(enabled_stmt)
        enabled_workflows = [row[0] for row in enabled_result.all()]

        # 如果没有启用的 workflow，返回空报告
        if not enabled_workflows:
            return CIDailyReport(
                date=date,
                summary={
                    "total_runs": 0,
                    "success_runs": 0,
                    "failure_runs": 0,
                    "success_rate": 0.0,
                    "avg_duration_seconds": None,
                },
                workflow_results=[],
                job_stats=[],
                markdown_report=f"# CI 每日报告\n\n## {date}\n\n暂无数据"
            )

        # 查询当天的 CI 结果 (使用 UTC 时间查询)
        stmt = select(CIResult).where(
            CIResult.started_at >= start_datetime_utc,
            CIResult.started_at < end_datetime_utc,
            CIResult.workflow_name.in_(enabled_workflows)
        ).order_by(CIResult.started_at.desc())

        result = await db.execute(stmt)
        ci_results = result.scalars().all()

        # 统计数据
        total_runs = len(ci_results)
        success_runs = sum(1 for r in ci_results if r.conclusion == "success")
        failure_runs = sum(1 for r in ci_results if r.conclusion in ["failure", "cancelled"])
        success_rate = round((success_runs / total_runs * 100) if total_runs > 0 else 0.0, 2)

        # 平均时长
        durations = [r.duration_seconds for r in ci_results if r.duration_seconds]
        avg_duration = round(sum(durations) / len(durations)) if durations else None

        # 按 workflow 分组统计
        workflow_stats = {}
        for r in ci_results:
            if r.workflow_name not in workflow_stats:
                workflow_stats[r.workflow_name] = {
                    "workflow_name": r.workflow_name,
                    "total_runs": 0,
                    "success_runs": 0,
                    "failure_runs": 0,
                    "avg_duration": None,
                    "latest_run": None,
                    "hardware": r.hardware,
                    "failed_jobs": [],  # 添加失败 job 列表
                    "total_jobs": 0,  # 总 job 数
                    "passed_jobs": 0,  # 通过 job 数
                }
            stats = workflow_stats[r.workflow_name]
            stats["total_runs"] += 1
            if r.conclusion == "success":
                stats["success_runs"] += 1
            elif r.conclusion in ["failure", "cancelled"]:
                stats["failure_runs"] += 1
            # 更新最新运行记录
            if not stats["latest_run"] or (r.started_at and r.started_at > stats["latest_run"]["started_at"]):
                # 转换为北京时间 (UTC+8)
                # 数据库存储的是 UTC 时间 (naive datetime),需要显式添加 UTC 时区信息后转换
                beijing_started_at = None
                if r.started_at:
                    # 如果 started_at 是 naive datetime，假设它是 UTC
                    if r.started_at.tzinfo is None:
                        utc_started_at = r.started_at.replace(tzinfo=UTC)
                    else:
                        utc_started_at = r.started_at
                    # 转换为北京时间
                    beijing_tz = timezone(timedelta(hours=8))
                    beijing_started_at = utc_started_at.astimezone(beijing_tz)

                stats["latest_run"] = {
                    "run_id": r.run_id,
                    "status": r.status,
                    "conclusion": r.conclusion,
                    "started_at": beijing_started_at.isoformat() if beijing_started_at else None,
                    "duration_seconds": r.duration_seconds,
                }

        # 查询失败 workflow 的 jobs 详情
        failed_run_ids = [r.run_id for r in ci_results if r.conclusion in ["failure", "cancelled"]]
        if failed_run_ids:
            jobs_stmt = select(CIJob).where(
                CIJob.run_id.in_(failed_run_ids),
                CIJob.conclusion.in_(["failure", "cancelled"])
            ).order_by(CIJob.workflow_name, CIJob.job_name)
            jobs_result = await db.execute(jobs_stmt)
            failed_jobs = jobs_result.scalars().all()

            # 获取 job 责任人
            job_names = list(set(f"{job.workflow_name}|||{job.job_name}" for job in failed_jobs))
            owners_stmt = select(JobOwner).where(
                JobOwner.workflow_name.in_([name.split("|||")[0] for name in job_names]),
                JobOwner.job_name.in_([name.split("|||")[1] for name in job_names])
            )
            owners_result = await db.execute(owners_stmt)
            job_owners_map = {}
            for owner in owners_result.scalars().all():
                key = f"{owner.workflow_name}|||{owner.job_name}"
                job_owners_map[key] = owner

            # 将失败 job 添加到对应的 workflow，并计算连续失败次数
            for job in failed_jobs:
                owner_key = f"{job.workflow_name}|||{job.job_name}"
                owner = job_owners_map.get(owner_key)

                # 查询该 job 的历史运行记录，计算连续失败次数
                consecutive_failures = 0
                job_history_stmt = select(CIJob).where(
                    CIJob.workflow_name == job.workflow_name,
                    CIJob.job_name == job.job_name
                ).order_by(CIJob.started_at.desc()).limit(20)  # 最多查最近 20 次
                job_history_result = await db.execute(job_history_stmt)
                job_history = job_history_result.scalars().all()

                # 计算连续失败次数（从最近一次开始，直到遇到成功为止）
                for hist_job in job_history:
                    if hist_job.conclusion in ["failure", "cancelled"]:
                        consecutive_failures += 1
                    else:
                        break

                failed_job_info = {
                    "job_name": job.job_name,
                    "conclusion": job.conclusion,
                    "duration_seconds": job.duration_seconds,
                    "github_url": f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{job.run_id}/job/{job.job_id}" if job.job_id else None,
                    "owner": owner.owner if owner else None,
                    "owner_email": owner.email if owner else None,
                    "consecutive_failures": consecutive_failures,  # 连续失败次数
                }
                workflow_stats[job.workflow_name]["failed_jobs"].append(failed_job_info)

        # 查询所有 job 以计算每个 workflow 的 job 通过率
        all_run_ids = [r.run_id for r in ci_results]
        if all_run_ids:
            all_jobs_stmt = select(CIJob).where(
                CIJob.run_id.in_(all_run_ids)
            )
            all_jobs_result = await db.execute(all_jobs_stmt)
            all_jobs = all_jobs_result.scalars().all()

            # 统计每个 workflow 的 job 数量
            for job in all_jobs:
                if job.workflow_name in workflow_stats:
                    workflow_stats[job.workflow_name]["total_jobs"] += 1
                    if job.conclusion == "success":
                        workflow_stats[job.workflow_name]["passed_jobs"] += 1

        # 计算每个 workflow 的平均时长
        workflow_durations = {}
        for r in ci_results:
            if r.duration_seconds:
                if r.workflow_name not in workflow_durations:
                    workflow_durations[r.workflow_name] = []
                workflow_durations[r.workflow_name].append(r.duration_seconds)

        for wf_name, durations in workflow_durations.items():
            if wf_name in workflow_stats:
                workflow_stats[wf_name]["avg_duration"] = round(sum(durations) / len(durations))

        # 转换为列表
        workflow_results = list(workflow_stats.values())

        # 生成 Markdown 报告
        markdown_lines = [
            "# CI 每日运行报告",
            "",
            f"## 📅 日期：{date}",
            "",
            "## 📊 总体统计",
            "",
            f"- **总运行次数**: {total_runs}",
            f"- **成功次数**: {success_runs}",
            f"- **失败次数**: {failure_runs}",
            f"- **成功率**: {success_rate}%",
            f"- **平均时长**: {avg_duration // 60}分{avg_duration % 60}秒" if avg_duration else "- **平均时长**: 无数据",
            "",
        ]

        if workflow_results:
            markdown_lines.extend([
                "## 🔧 Workflow 详情",
                "",
            ])

            for wf in sorted(workflow_results, key=lambda x: x["workflow_name"]):
                hw_tag = f" ({wf['hardware']})" if wf.get('hardware') and wf['hardware'] != 'unknown' else ""
                # 使用 job 通过率计算成功率
                job_success_rate = round((wf["passed_jobs"] / wf["total_jobs"] * 100) if wf["total_jobs"] > 0 else 0.0, 2)
                avg_dur_str = f"{wf['avg_duration'] // 60}分{wf['avg_duration'] % 60}秒" if wf['avg_duration'] else "无数据"

                markdown_lines.extend([
                    f"### {wf['workflow_name']}{hw_tag}",
                    "",
                    f"- 运行次数：{wf['total_runs']}",
                    f"- Job 通过率：{job_success_rate}% ({wf['passed_jobs']}/{wf['total_jobs']})",
                    f"- 平均时长：{avg_dur_str}",
                ])

                # 添加失败 job 详情
                if wf.get('failed_jobs') and len(wf['failed_jobs']) > 0:
                    markdown_lines.extend([
                        "",
                        "**❌ 失败 Job 详情:**",
                        "",
                    ])
                    for job in wf['failed_jobs']:
                        duration_str = f"{job['duration_seconds'] // 60}分{job['duration_seconds'] % 60}秒" if job['duration_seconds'] else "N/A"
                        owner_info = f"**{job['owner']}**" if job.get('owner') else "未配置责任人"
                        if job.get('owner_email'):
                            owner_info += f" ({job['owner_email']})"

                        # 连续失败次数标记
                        consecutive_failures = job.get('consecutive_failures', 0)
                        if consecutive_failures > 0:
                            if consecutive_failures >= 5:
                                failure_flag = f"🔥 **连续失败 {consecutive_failures} 次**"
                            elif consecutive_failures >= 3:
                                failure_flag = f"⚠️ 连续失败 {consecutive_failures} 次"
                            else:
                                failure_flag = f"连续失败 {consecutive_failures} 次"
                        else:
                            failure_flag = ""

                        github_link = f"[查看 Job]({job['github_url']})" if job.get('github_url') else "无链接"

                        markdown_lines.extend([
                            f"- **{job['job_name']}**: {job['conclusion']} | 时长：{duration_str} | 责任人：{owner_info} | {failure_flag + ' | ' if failure_flag else ''}{github_link}",
                        ])

                markdown_lines.append("")

        # 添加总结
        markdown_lines.extend([
            "## 📝 总结",
            "",
        ])

        if total_runs == 0:
            markdown_lines.append("当日暂无 CI 运行记录。")

        # 添加失败 job 汇总
        total_failed_jobs = sum(len(wf.get('failed_jobs', [])) for wf in workflow_results)
        if total_failed_jobs > 0:
            markdown_lines.extend([
                "",
                f"当日共有 **{total_failed_jobs}** 个失败 Job，请相关责任人及时跟进处理。",
            ])

        markdown_report = "\n".join(markdown_lines)

        return CIDailyReport(
            date=date,
            summary={
                "total_runs": total_runs,
                "success_runs": success_runs,
                "failure_runs": failure_runs,
                "success_rate": success_rate,
                "avg_duration_seconds": avg_duration,
            },
            workflow_results=workflow_results,
            markdown_report=markdown_report,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}"
        )


# ============ Failure Analysis API ============

@router.post("/failure-analysis/analyze/{job_id}")
async def analyze_failed_job(
    job_id: int,
    current_user: CurrentAdminUser,
    db: DbSession,
    force: bool = Query(default=False, description="强制重新分析"),
):
    """触发失败分析（异步后台执行，立即返回，前端轮询 GET 接口获取结果）"""
    import asyncio

    from sqlalchemy import delete, text

    from app.db.base import SessionLocal
    from app.models import CIJob, JobFailureAnalysis
    from app.services.failure_analysis import FailureAnalysisService

    # 1. 验证 job 存在
    stmt = select(CIJob).where(CIJob.job_id == job_id)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CIJob with job_id={job_id} not found")
    if job.conclusion not in ("failure", "cancelled"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Job conclusion is '{job.conclusion}', not a failed job")

    # 2. 检查已有记录
    existing_stmt = select(JobFailureAnalysis).where(
        JobFailureAnalysis.job_id == job_id
    ).order_by(JobFailureAnalysis.id.desc()).limit(1)
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()

    # 2a. 分析进行中 → 直接返回，让前端轮询（force 也不允许重复提交）
    if existing and existing.analysis_status == "analyzing":
        return existing

    # 2b. 已完成且非 force → 直接返回缓存
    if existing and existing.analysis_status in ("completed", "reused") and not force:
        return existing

    # 3. force 模式下清理旧记录（已完成/失败的可重跑）
    if force and existing:
        try:
            await db.execute(text("SET SESSION innodb_lock_wait_timeout = 2"))
        except Exception:
            pass
        del_stmt = delete(JobFailureAnalysis).where(JobFailureAnalysis.job_id == job_id)
        await db.execute(del_stmt)
        await db.flush()

    # 4. 创建 "analyzing" 占位记录，立即返回
    service = FailureAnalysisService()
    fingerprint = service.compute_failure_fingerprint(job)
    placeholder = JobFailureAnalysis(
        job_id=job_id,
        run_id=job.run_id,
        workflow_name=job.workflow_name,
        job_name=job.job_name,
        failure_date=job.completed_at or datetime.now(UTC),
        failure_fingerprint=fingerprint,
        analysis_status="analyzing",
    )
    db.add(placeholder)
    await db.commit()
    await db.refresh(placeholder)

    # 5. 后台异步执行实际分析
    async def _run_analysis():
        async with SessionLocal() as bg_db:
            svc = FailureAnalysisService()
            try:
                await svc.analyze_failed_job(job_id=job_id, db=bg_db, force=force, triggered_by="manual")
            except Exception as e:
                logger.error(f"Background analysis failed for job {job_id}: {e}")
                # 确保状态更新为 failed，避免僵尸记录
                try:
                    from sqlalchemy import update
                    await bg_db.execute(
                        update(JobFailureAnalysis)
                        .where(JobFailureAnalysis.job_id == job_id)
                        .values(analysis_status="failed", error_message=str(e)[:500])
                    )
                    await bg_db.commit()
                except Exception as db_e:
                    logger.error(f"Failed to update analysis status for job {job_id}: {db_e}")

    asyncio.create_task(_run_analysis())
    return placeholder


@router.post("/failure-analysis/analyze-batch")
async def analyze_batch(
    current_user: CurrentAdminUser,
    db: DbSession,
    days_back: int = Query(default=7, description="分析最近N天的失败Job"),
):
    from app.services.failure_analysis import FailureAnalysisService
    service = FailureAnalysisService()
    try:
        results = await service.analyze_batch(days_back=days_back, db=db)
        return {
            "success": True,
            "message": f"分析完成，共处理 {len(results)} 个失败Job",
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"Failed to analyze batch: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"批量分析失败: {str(e)}")


@router.get("/failure-analysis/list", response_model=FailureAnalysisListResponse)
async def list_failure_analyses(
    problem_category: str | None = Query(default=None),
    analysis_status_filter: str | None = Query(default=None, alias="analysis_status"),
    workflow_name: str | None = Query(default=None),
    days_back: int | None = Query(default=7),
    db: DbSession = None,
):
    from app.services.failure_analysis import FailureAnalysisService
    service = FailureAnalysisService()
    filters = {}
    if problem_category:
        filters["problem_category"] = problem_category
    if analysis_status_filter:
        filters["analysis_status"] = analysis_status_filter
    if workflow_name:
        filters["workflow_name"] = workflow_name
    if days_back:
        filters["days_back"] = days_back
    return await service.list_analyses(filters=filters, db=db)


@router.get("/failure-analysis/{analysis_id}", response_model=FailureAnalysisResponse)
async def get_failure_analysis(
    analysis_id: int,
    db: DbSession,
):
    from app.services.failure_analysis import FailureAnalysisService
    service = FailureAnalysisService()
    analysis = await service.get_analysis(analysis_id=analysis_id, db=db)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分析记录不存在")
    return analysis


@router.get("/failure-analysis/{analysis_id}/report")
async def get_failure_analysis_report(
    analysis_id: int,
    db: DbSession,
):
    from app.services.failure_analysis import FailureAnalysisService
    service = FailureAnalysisService()
    analysis = await service.get_analysis(analysis_id=analysis_id, db=db)
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分析记录不存在")
    if not analysis.report_file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件不存在")
    from app.services.failure_analysis_file_store import FailureAnalysisFileStore
    file_store = FailureAnalysisFileStore()
    content = await file_store.read_report_by_path(analysis.report_file_path)
    if not content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件读取失败")
    return {"content": content, "analysis_id": analysis_id}


@router.get("/jobs/{job_id}/failure-analysis", response_model=FailureAnalysisResponse | None)
async def get_job_failure_analysis(
    job_id: int,
    db: DbSession,
):
    from app.services.failure_analysis import FailureAnalysisService
    service = FailureAnalysisService()
    analysis = await service.get_analysis_by_job_id(job_id=job_id, db=db)
    if not analysis:
        return None
    return analysis


# ============ Claude Code CLI 日志 ============


@router.get("/claude-logs")
async def list_claude_logs(
    current_user: CurrentAdminUser,
    days: int = Query(default=7, ge=1, le=30),
):
    """列出最近 N 天的 Claude Code CLI 调用日志（需 admin）"""
    from app.services.claude_code_cli import _CLI_LOG_DIR

    logs: list[dict] = []
    if not _CLI_LOG_DIR.exists():
        return {"logs": [], "message": "No logs yet"}

    cutoff = datetime.now(timezone.utc).date()
    for date_dir in sorted(_CLI_LOG_DIR.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        dir_date = date_dir.name[:10]
        if (cutoff - datetime.strptime(dir_date, "%Y-%m-%d").date()).days > days:
            continue
        for log_file in sorted(date_dir.iterdir(), reverse=True):
            if log_file.suffix == ".log":
                stat = log_file.stat()
                logs.append({
                    "date": dir_date,
                    "filename": log_file.name,
                    "path": str(log_file.relative_to(_CLI_LOG_DIR)),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                })

    return {"total": len(logs), "logs": logs}


@router.get("/claude-logs/{date}/{filename}")
async def read_claude_log(
    date: str,
    filename: str,
    current_user: CurrentAdminUser,
):
    """读取指定的 Claude Code CLI 日志文件内容"""
    from app.services.claude_code_cli import _CLI_LOG_DIR

    filepath = _CLI_LOG_DIR / date / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    content = filepath.read_text(encoding="utf-8")
    return {"filename": filename, "content": content}


# ============ Claude Code CLI Config ============

@router.get("/claude-cli-config")
async def get_claude_cli_config(
    current_user: CurrentAdminUser,
    db: DbSession,
):
    """获取 Claude Code CLI 配置（max_turns、timeout）"""
    from app.models import ProjectDashboardConfig

    stmt = select(ProjectDashboardConfig).where(
        ProjectDashboardConfig.config_key == "claude_code_cli_config"
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row and row.config_value:
        return dict(row.config_value)
    return {"max_turns": 80, "timeout_seconds": 1800}


@router.put("/claude-cli-config")
async def update_claude_cli_config(
    data: dict,
    current_user: CurrentAdminUser,
    db: DbSession,
):
    """更新 Claude Code CLI 配置"""
    from app.models import ProjectDashboardConfig

    max_turns = data.get("max_turns", 80)
    timeout_seconds = data.get("timeout_seconds", 1800)
    config_value = {"max_turns": max_turns, "timeout_seconds": timeout_seconds}

    stmt = select(ProjectDashboardConfig).where(
        ProjectDashboardConfig.config_key == "claude_code_cli_config"
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        row.config_value = config_value
    else:
        row = ProjectDashboardConfig(config_key="claude_code_cli_config", config_value=config_value)
        db.add(row)
    await db.commit()
    return config_value
