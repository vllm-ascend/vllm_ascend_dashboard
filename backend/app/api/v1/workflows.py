"""
Workflow 配置管理 API
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import WorkflowConfig
from app.schemas import WorkflowConfigCreate, WorkflowConfigResponse, WorkflowConfigUpdate

router = APIRouter()


@router.get("", response_model=list[WorkflowConfigResponse])
async def list_workflows(
    db: DbSession,
    enabled: bool | None = Query(None, description="是否只获取启用的 workflow"),
):
    """获取所有 workflow 配置"""
    stmt = select(WorkflowConfig).order_by(WorkflowConfig.display_order, WorkflowConfig.id)

    if enabled is not None:
        stmt = stmt.where(WorkflowConfig.enabled == enabled)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{workflow_id}", response_model=WorkflowConfigResponse)
async def get_workflow(
    workflow_id: int,
    db: DbSession
):
    """获取单个 workflow 配置"""
    stmt = select(WorkflowConfig).where(WorkflowConfig.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} 不存在"
        )

    return workflow


@router.post("", response_model=WorkflowConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow_data: WorkflowConfigCreate,
    db: DbSession
):
    """创建新的 workflow 配置"""
    # 去除首尾空格
    workflow_name = workflow_data.workflow_name.strip()
    workflow_file = workflow_data.workflow_file.strip()
    
    # 检查 workflow_name 是否已存在
    stmt = select(WorkflowConfig).where(WorkflowConfig.workflow_name == workflow_name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow 名称 '{workflow_name}' 已存在"
        )

    # 检查 workflow_file 是否已存在
    stmt = select(WorkflowConfig).where(WorkflowConfig.workflow_file == workflow_file)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow 文件 '{workflow_file}' 已存在"
        )

    workflow = WorkflowConfig(
        workflow_name=workflow_name,
        workflow_file=workflow_file,
        hardware=workflow_data.hardware,
        event=workflow_data.event if workflow_data.event is not None else "schedule",
        actor=workflow_data.actor,
        description=workflow_data.description,
        enabled=workflow_data.enabled,
        display_order=workflow_data.display_order,
        stats_start_hour=workflow_data.stats_start_hour,
        stats_end_hour=workflow_data.stats_end_hour,
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    return workflow


@router.put("/{workflow_id}", response_model=WorkflowConfigResponse)
async def update_workflow(
    workflow_id: int,
    workflow_data: WorkflowConfigUpdate,
    db: DbSession
):
    """更新 workflow 配置"""
    stmt = select(WorkflowConfig).where(WorkflowConfig.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} 不存在"
        )

    # 更新字段（去除首尾空格）
    update_data = workflow_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(workflow, field, value)

    await db.commit()
    await db.refresh(workflow)

    return workflow


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    db: DbSession
):
    """删除 workflow 配置"""
    stmt = select(WorkflowConfig).where(WorkflowConfig.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} 不存在"
        )

    await db.delete(workflow)
    await db.commit()

    return {"message": f"Workflow {workflow_id} 已成功删除"}


@router.post("/{workflow_id}/toggle")
async def toggle_workflow(
    workflow_id: int,
    db: DbSession
):
    """切换 workflow 启用/禁用状态"""
    stmt = select(WorkflowConfig).where(WorkflowConfig.id == workflow_id)
    result = await db.execute(stmt)
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} 不存在"
        )

    workflow.enabled = not workflow.enabled
    await db.commit()
    await db.refresh(workflow)

    return {
        "message": f"Workflow {workflow.workflow_name} 已{'启用' if workflow.enabled else '禁用'}",
        "enabled": workflow.enabled
    }
