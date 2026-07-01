"""
Job 责任人管理 API
"""
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select

from app.api.deps import DbSession
from app.models import CIJob, JobOwner, WorkflowConfig
from app.schemas import (
    CIJobResponse,
    JobOwnerCreate,
    JobOwnerResponse,
    JobOwnerUpdate,
    JobStats,
)

router = APIRouter()


@router.get("/hidden", response_model=list[JobOwnerResponse])
async def list_hidden_jobs(
    db: DbSession
):
    """获取所有隐藏的 Job（通过 JobOwner.is_hidden 字段）"""
    stmt = select(JobOwner).where(JobOwner.is_hidden == True).order_by(JobOwner.workflow_name, JobOwner.job_name)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/toggle-hidden", response_model=JobOwnerResponse)
async def toggle_job_hidden(
    workflow_name: str = Query(..., description="Workflow 名称"),
    job_name: str = Query(..., description="Job 名称"),
    is_hidden: bool = Query(..., description="是否隐藏"),
    db: DbSession = None  # type: ignore
):
    """切换 Job 可见性状态（通过 JobOwner.is_hidden 字段）"""
    # 查找现有记录
    stmt = select(JobOwner).where(
        JobOwner.workflow_name == workflow_name,
        JobOwner.job_name == job_name
    )
    result = await db.execute(stmt)
    owner = result.scalar_one_or_none()

    if owner:
        # 更新现有记录
        owner.is_hidden = is_hidden
        await db.commit()
        await db.refresh(owner)
    else:
        # 创建新记录（用于隐藏无责任人的 job）
        owner = JobOwner(
            workflow_name=workflow_name,
            job_name=job_name,
            owner='_system_hidden',
            is_hidden=is_hidden
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)

    return owner


@router.get("", response_model=list[JobOwnerResponse])
async def list_job_owners(
    db: DbSession,
    workflow_name: str | None = Query(None, description="按 workflow 名称筛选"),
):
    """获取所有 Job 责任人配置"""
    stmt = select(JobOwner).order_by(JobOwner.workflow_name, JobOwner.job_name)

    if workflow_name:
        stmt = stmt.where(JobOwner.workflow_name == workflow_name)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/available-jobs", response_model=list[dict])
async def get_available_jobs(
    db: DbSession,
    workflow_name: str | None = Query(None, description="按 workflow 名称筛选"),
):
    """获取所有可用的 job 列表（从 CIJob 表中获取不重复的 workflow_name + job_name 组合）
    只返回启用的 workflow 的 job
    """
    # 获取启用的 workflow 名称列表
    enabled_stmt = select(WorkflowConfig.workflow_name).where(WorkflowConfig.enabled == True)
    if workflow_name:
        enabled_stmt = enabled_stmt.where(WorkflowConfig.workflow_name == workflow_name)
    enabled_result = await db.execute(enabled_stmt)
    enabled_workflows = [row[0] for row in enabled_result.all()]

    # 如果没有启用的 workflow，直接返回空列表
    if not enabled_workflows:
        return []

    stmt = select(
        CIJob.workflow_name,
        CIJob.job_name
    ).where(
        CIJob.workflow_name.in_(enabled_workflows)
    ).distinct()

    if workflow_name:
        stmt = stmt.where(CIJob.workflow_name == workflow_name)

    stmt = stmt.order_by(CIJob.workflow_name, CIJob.job_name)

    result = await db.execute(stmt)
    return [
        {"workflow_name": row.workflow_name, "job_name": row.job_name}
        for row in result.all()
    ]


@router.get("/jobs/runs", response_model=list[CIJobResponse])
async def list_job_runs(
    db: DbSession,
    workflow_name: str = Query(..., description="Workflow 名称"),
    job_name: str = Query(..., description="Job 名称"),
    limit: int = Query(100, ge=1, le=500, description="最多返回多少条记录"),
    days: int | None = Query(None, ge=1, le=365, description="最近多少天的数据，不传则返回全部"),
):
    """获取指定 job 的所有运行记录（默认返回全部数据）"""
    stmt = select(CIJob).where(
        CIJob.workflow_name == workflow_name,
        CIJob.job_name == job_name,
    )

    # 如果指定了天数，添加时间过滤
    if days is not None:
        start_date = datetime.now(UTC) - timedelta(days=days)
        stmt = stmt.where(CIJob.started_at >= start_date)

    stmt = stmt.order_by(
        CIJob.started_at.desc()
    ).limit(limit)

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


@router.get("/{owner_id}", response_model=JobOwnerResponse)
async def get_job_owner(
    owner_id: int,
    db: DbSession
):
    """获取单个 Job 责任人配置"""
    stmt = select(JobOwner).where(JobOwner.id == owner_id)
    result = await db.execute(stmt)
    owner = result.scalar_one_or_none()

    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job Owner {owner_id} 不存在"
        )

    return owner


@router.post("", response_model=JobOwnerResponse, status_code=status.HTTP_201_CREATED)
async def create_job_owner(
    owner_data: JobOwnerCreate,
    db: DbSession
):
    """创建新的 Job 责任人配置"""
    # 检查 workflow_name + job_name 是否已存在
    stmt = select(JobOwner).where(
        JobOwner.workflow_name == owner_data.workflow_name,
        JobOwner.job_name == owner_data.job_name
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow '{owner_data.workflow_name}' 的 Job '{owner_data.job_name}' 已配置责任人"
        )

    owner = JobOwner(**owner_data.model_dump())
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    return owner


@router.put("/{owner_id}", response_model=JobOwnerResponse)
async def update_job_owner(
    owner_id: int,
    owner_data: JobOwnerUpdate,
    db: DbSession
):
    """更新 Job 责任人配置"""
    stmt = select(JobOwner).where(JobOwner.id == owner_id)
    result = await db.execute(stmt)
    owner = result.scalar_one_or_none()

    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job Owner {owner_id} 不存在"
        )

    # 更新字段
    update_data = owner_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(owner, field, value)

    await db.commit()
    await db.refresh(owner)

    return owner


@router.delete("/{owner_id}")
async def delete_job_owner(
    owner_id: int,
    db: DbSession
):
    """删除 Job 责任人配置"""
    stmt = select(JobOwner).where(JobOwner.id == owner_id)
    result = await db.execute(stmt)
    owner = result.scalar_one_or_none()

    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job Owner {owner_id} 不存在"
        )

    await db.delete(owner)
    await db.commit()

    return {"message": f"Job Owner {owner_id} 已成功删除"}


@router.post("/{owner_id}/toggle-hidden")
async def toggle_job_hidden(
    owner_id: int,
    db: DbSession
):
    """切换 Job 隐藏/显示状态"""
    stmt = select(JobOwner).where(JobOwner.id == owner_id)
    result = await db.execute(stmt)
    owner = result.scalar_one_or_none()

    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job Owner {owner_id} 不存在"
        )

    owner.is_hidden = not owner.is_hidden
    await db.commit()
    await db.refresh(owner)

    return {
        "message": f"Job {owner.workflow_name}/{owner.job_name} 已{'隐藏' if owner.is_hidden else '显示'}",
        "is_hidden": owner.is_hidden
    }


@router.get("/stats/job-summary", response_model=list[JobStats])
async def get_job_summary_stats(
    db: DbSession,
    days: int | None = Query(None, ge=1, le=365, description="统计最近多少天的数据，不传则统计全部数据"),
    workflow_name: str | None = Query(None, description="按 workflow 名称筛选"),
    job_name: str | None = Query(None, description="按 job 名称筛选"),
):
    """
    获取 Job 汇总统计数据

    按 workflow_name + job_name 分组，统计总运行次数、成功率、平均时长等
    只统计启用的 workflow 的 job 数据
    """
    # 计算起始时间
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days) if days is not None else None

    # 获取启用的 workflow 配置（含时间窗口）
    enabled_stmt = select(
        WorkflowConfig.workflow_name,
        WorkflowConfig.stats_start_hour,
        WorkflowConfig.stats_end_hour,
    ).where(WorkflowConfig.enabled == True)
    if workflow_name:
        enabled_stmt = enabled_stmt.where(WorkflowConfig.workflow_name == workflow_name)
    enabled_result = await db.execute(enabled_stmt)
    wf_configs = [(row[0], row[1], row[2]) for row in enabled_result.all()]
    enabled_workflows = [wc[0] for wc in wf_configs]

    # 如果没有启用的 workflow，直接返回空列表
    if not enabled_workflows:
        return []

    # 构建按 workflow 的时间窗口过滤条件
    wf_filter_conditions = []
    for wf_name, start_h, end_h in wf_configs:
        wf_cond = CIJob.workflow_name == wf_name
        if start_h is not None and end_h is not None:
            hour_expr = func.hour(CIJob.started_at)
            if start_h >= end_h:
                wf_cond = and_(wf_cond, or_(hour_expr >= start_h, hour_expr < end_h))
            else:
                wf_cond = and_(wf_cond, hour_expr >= start_h, hour_expr < end_h)
        wf_filter_conditions.append(wf_cond)
    wf_filter = or_(*wf_filter_conditions) if wf_filter_conditions else None

    # 构建基础查询
    stmt = select(
        CIJob.workflow_name,
        CIJob.job_name,
        func.count().label('total_runs'),
        func.sum(
            case(
                (CIJob.conclusion == "success", 1),
                else_=0
            )
        ).label('success_runs'),
        func.sum(
            case(
                (CIJob.conclusion == "failure", 1),
                else_=0
            )
        ).label('failure_runs'),
        func.avg(CIJob.duration_seconds).label('avg_duration'),
        func.min(CIJob.duration_seconds).label('min_duration'),
        func.max(CIJob.duration_seconds).label('max_duration'),
        func.max(CIJob.started_at).label('last_run_at'),
    )

    # 添加时间过滤条件（如果指定了 days）
    time_filters = [CIJob.started_at <= end_date, CIJob.duration_seconds.isnot(None)]
    if start_date:
        time_filters.append(CIJob.started_at >= start_date)

    stmt = stmt.where(
        *time_filters,
        wf_filter,
    )

    if workflow_name:
        stmt = stmt.where(CIJob.workflow_name == workflow_name)
    if job_name:
        stmt = stmt.where(CIJob.job_name == job_name)

    stmt = stmt.group_by(
        CIJob.workflow_name,
        CIJob.job_name
    ).order_by(
        CIJob.workflow_name,
        CIJob.job_name
    )

    result = await db.execute(stmt)
    rows = result.all()

    # 获取所有 job 的最新状态（用于 last_status 和 last_conclusion）
    # 使用 INNER JOIN on max 替代关联子查询，性能提升 1400 倍
    latest_filters = [CIJob.started_at <= end_date]
    if start_date:
        latest_filters.append(CIJob.started_at >= start_date)

    latest_max_stmt = select(
        CIJob.workflow_name,
        CIJob.job_name,
        func.max(CIJob.started_at).label('max_started_at'),
    ).where(
        *latest_filters,
        wf_filter,
    )

    if workflow_name:
        latest_max_stmt = latest_max_stmt.where(CIJob.workflow_name == workflow_name)
    if job_name:
        latest_max_stmt = latest_max_stmt.where(CIJob.job_name == job_name)

    latest_max_stmt = latest_max_stmt.group_by(
        CIJob.workflow_name, CIJob.job_name
    ).subquery()

    latest_jobs_stmt = select(
        CIJob.workflow_name,
        CIJob.job_name,
        CIJob.status.label('latest_status'),
        CIJob.conclusion.label('latest_conclusion'),
    ).join(
        latest_max_stmt,
        and_(
            CIJob.workflow_name == latest_max_stmt.c.workflow_name,
            CIJob.job_name == latest_max_stmt.c.job_name,
            CIJob.started_at == latest_max_stmt.c.max_started_at,
        ),
    )

    if workflow_name:
        latest_jobs_stmt = latest_jobs_stmt.where(CIJob.workflow_name == workflow_name)
    if job_name:
        latest_jobs_stmt = latest_jobs_stmt.where(CIJob.job_name == job_name)

    latest_result = await db.execute(latest_jobs_stmt)
    latest_jobs_map = {
        (row.workflow_name, row.job_name): {
            'status': row.latest_status,
            'conclusion': row.latest_conclusion
        }
        for row in latest_result.all()
    }

    # 获取责任人配置
    owners_stmt = select(JobOwner)
    owners_result = await db.execute(owners_stmt)
    owners_map = {
        (owner.workflow_name, owner.job_name): owner
        for owner in owners_result.scalars().all()
    }

    # 转换为响应格式
    stats = []
    for row in rows:
        key = (row.workflow_name, row.job_name)
        owner = owners_map.get(key)
        latest_job = latest_jobs_map.get(key, {})

        total_runs = row.total_runs
        success_runs = row.success_runs
        success_rate = round(success_runs / total_runs * 100, 2) if total_runs > 0 else 0.0

        stats.append(JobStats(
            workflow_name=row.workflow_name,
            job_name=row.job_name,
            display_name=owner.display_name if owner else None,
            owner=owner.owner if owner else None,
            owner_email=owner.email if owner else None,
            total_runs=total_runs,
            success_runs=success_runs,
            failure_runs=row.failure_runs,
            success_rate=success_rate,
            avg_duration_seconds=float(row.avg_duration) if row.avg_duration else None,
            min_duration_seconds=row.min_duration,
            max_duration_seconds=row.max_duration,
            last_run_at=row.last_run_at,
            last_status=latest_job.get('status'),
            last_conclusion=latest_job.get('conclusion'),
        ))

    return stats
