"""
Project Dashboard API 路由
提供项目看板相关的数据和功能
"""
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_admin_user, get_current_user, get_db as get_db_session
from app.db.base import get_db
from app.models import User
from app.schemas import (
    CommitInfo,
    ModelSupportEntry,
    ModelSupportMatrix,
    PRActionRequest,
    ProjectDashboardConfigResponse,
    ProjectDashboardConfigUpdate,
    ReleaseInfo,
    StaleIssue,
    TagComparisonRequest,
    TagComparisonResult,
    VllmVersionInfo,
)
from app.services.github_api import get_github_api_service
from app.services.github_cache import ensure_repo_cloned, get_github_cache, update_repo
from app.services.project_dashboard import get_project_dashboard_service

logger = logging.getLogger(__name__)

router = APIRouter()


# 移除本地的 _get_db 函数，统一使用 deps.py 中的 get_db


@router.get("/releases")
async def get_releases(
    recommended: bool = Query(False, description="是否只返回推荐版本（最新 2 个 stable + 最新 1 个 pre-release）")
):
    """
    获取 stable 和 pre-release 版本号及 docker pull 命令

    不需要登录即可访问

    Args:
        recommended: 如果为 true，只返回推荐版本（最新 2 个 stable + 最新 1 个 pre-release）
    """
    # Ensure repo is cloned
    if not ensure_repo_cloned():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clone repository",
        )

    service = get_project_dashboard_service()
    releases = service.get_releases(recommended_only=recommended)

    # Convert to ReleaseInfo format
    result = []
    for release in releases:
        result.append({
            "version": release["version"],
            "is_stable": release["is_stable"],
            "published_at": release["published_at"],
            "docker_commands": release["docker_commands"],
        })

    return {"releases": result}


@router.get("/versions/main")
async def get_main_versions():
    """
    获取 main 分支当前支持的 vllm 版本信息

    从 conf.py 的 myst_substitutions 中提取
    """
    # Ensure repo is cloned
    if not ensure_repo_cloned():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clone repository",
        )

    service = get_project_dashboard_service()
    versions = service.get_main_branch_versions()

    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failed to fetch version information",
        )

    return versions


@router.get("/tags")
async def get_all_tags():
    """
    获取所有 tags 列表

    用于 Tag 对比功能选择
    """
    # Ensure repo is cloned
    if not ensure_repo_cloned():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clone repository",
        )

    service = get_project_dashboard_service()
    tags = service.get_all_tags()

    return {"tags": tags}

@router.get("/model-support-matrix")
async def get_model_support_matrix(
    db: Annotated[Any, Depends(get_db_session)]
):
    """
    获取模型支持矩阵信息

    从数据库配置中读取
    """
    from sqlalchemy import select
    from app.models import ProjectDashboardConfig

    # 从数据库读取配置
    stmt = select(ProjectDashboardConfig).where(
        ProjectDashboardConfig.config_key == "model_support_matrix"
    )
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if config:
        return {
            "entries": config.config_value.get("entries", []),
            "featureColumns": config.config_value.get("featureColumns", []),
            "source_url": "",
            "updated_at": config.updated_at.isoformat() if config.updated_at else "",
        }
    else:
        # 返回空结果而不是 404
        return {
            "entries": [],
            "featureColumns": [],
            "source_url": "",
            "updated_at": "",
        }


@router.put("/model-support-matrix")
async def update_model_support_matrix(
    data: Dict[str, Any],
    db: Annotated[Any, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_active_admin_user)]
):
    """
    更新模型支持矩阵

    仅管理员可修改，配置保存在系统设置中
    """
    from sqlalchemy import select

    from app.models import ProjectDashboardConfig

    entries = data.get("entries", [])
    featureColumns = data.get("featureColumns")

    # Validate entries
    try:
        validated_entries = []
        for entry in entries:
            validated_entries.append({
                "model_name": entry.get("model_name", ""),
                "series": entry.get("series", "Other"),
                "support": entry.get("support", "supported"),
                "note": entry.get("note"),
                "doc_link": entry.get("doc_link"),
                "weight_format": entry.get("weight_format"),
                "kv_cache_type": entry.get("kv_cache_type"),
                "supported_hardware": entry.get("supported_hardware"),
                "chunked_prefill": entry.get("chunked_prefill"),
                "automatic_prefix_cache": entry.get("automatic_prefix_cache"),
                "lora": entry.get("lora"),
                "speculative_decoding": entry.get("speculative_decoding"),
                "async_scheduling": entry.get("async_scheduling"),
                "tensor_parallel": entry.get("tensor_parallel"),
                "pipeline_parallel": entry.get("pipeline_parallel"),
                "expert_parallel": entry.get("expert_parallel"),
                "data_parallel": entry.get("data_parallel"),
                "prefilled_decode_disaggregation": entry.get("prefilled_decode_disaggregation"),
                "piecewise_aclgraph": entry.get("piecewise_aclgraph"),
                "fullgraph_aclgraph": entry.get("fullgraph_aclgraph"),
                "max_model_len": entry.get("max_model_len"),
                "mlp_weight_prefetch": entry.get("mlp_weight_prefetch"),
            })
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid entry format: {str(e)}",
        )

    # Save to database
    try:
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == "model_support_matrix"
        )
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()

        config_value = {"entries": validated_entries}
        if featureColumns is not None:
            config_value["featureColumns"] = featureColumns

        if config:
            config.config_value = config_value
            config.description = "模型支持矩阵配置"
        else:
            config = ProjectDashboardConfig(
                config_key="model_support_matrix",
                config_value=config_value,
                description="模型支持矩阵配置",
            )
            db.add(config)

        await db.commit()

        return {"success": True, "message": "模型支持矩阵已更新"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save configuration: {str(e)}",
        )


@router.get("/stale-issues")
async def get_stale_issues(
    days: int = Query(7, ge=1, le=30, description="天数阈值"),
    current_user: Annotated[User, Depends(get_current_user)] = None
):
    """
    获取超期未 review 或处理的 issue 和 PR

    以最后更新时间为准，默认 7 天
    """
    github_api = get_github_api_service()

    if not github_api.token:
        logger.warning("GitHub token not configured, returning empty stale issues")
        return {"issues": [], "prs": [], "days_threshold": days}

    result = await github_api.get_stale_issues_and_prs(days)

    return {"issues": result["issues"], "prs": result["prs"], "days_threshold": days}


@router.get("/pr/{pr_number}/ci-status")
async def get_pr_ci_status(
    pr_number: int,
    current_user: Annotated[User, Depends(get_current_user)] = None
):
    """
    获取 PR 的 CI 状态

    使用 workflow runs API 获取 PR 的 CI 检查结果
    """
    logger.info(f"CI status requested for PR #{pr_number} by user {current_user.username}")

    github_api = get_github_api_service()

    if not github_api.token:
        logger.error(f"GitHub token not configured for PR #{pr_number}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub token not configured",
        )

    # Get PR info
    pr_info = await github_api.get_pr(pr_number)
    if not pr_info:
        logger.error(f"PR #{pr_number} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PR #{pr_number} not found",
        )
    
    logger.info(f"PR #{pr_number} info: title={pr_info.get('title')}, state={pr_info.get('state')}, head_ref={pr_info.get('head', {}).get('ref')}")

    # Get workflow runs for this PR
    logger.info(f"Fetching workflow runs for PR #{pr_number}...")
    workflow_runs = await github_api.get_workflow_runs_for_pr(pr_number)
    logger.info(f"Found {len(workflow_runs)} workflow runs for PR #{pr_number}")
    
    # Log workflow run details for debugging
    for i, run in enumerate(workflow_runs[:5]):
        logger.info(f"Workflow run {i}: id={run.get('id')}, name={run.get('name')}, "
                   f"status={run.get('status')}, conclusion={run.get('conclusion')}, "
                   f"head_sha={run.get('head_sha')}")

    # Categorize workflow runs by status
    in_progress_runs = [run for run in workflow_runs if run.get("status") == "in_progress"]
    queued_runs = [run for run in workflow_runs if run.get("status") == "queued"]
    completed_runs = [run for run in workflow_runs if run.get("status") == "completed"]

    # Find failed and successful runs
    failed_runs = [run for run in completed_runs if run.get("conclusion") == "failure"]
    success_runs = [run for run in completed_runs if run.get("conclusion") == "success"]
    skipped_runs = [run for run in completed_runs if run.get("conclusion") == "skipped"]
    
    logger.info(f"Categorized: in_progress={len(in_progress_runs)}, queued={len(queued_runs)}, "
               f"completed={len(completed_runs)}, failed={len(failed_runs)}, "
               f"success={len(success_runs)}, skipped={len(skipped_runs)}")

    return {
        "pr_number": pr_number,
        "pr_title": pr_info.get("title"),
        "pr_state": pr_info.get("state"),
        "pr_url": pr_info.get("html_url"),
        "workflow_runs": {
            "in_progress": in_progress_runs,
            "queued": queued_runs,
            "completed": completed_runs,
            "failed": failed_runs,
            "success": success_runs,
            "skipped": skipped_runs,
        },
        "summary": {
            "total": len(workflow_runs),
            "in_progress": len(in_progress_runs),
            "queued": len(queued_runs),
            "completed": len(completed_runs),
            "failed": len(failed_runs),
            "success": len(success_runs),
            "skipped": len(skipped_runs),
        }
    }


@router.post("/pr/{pr_number}/rerun-ci")
async def rerun_pr_ci(
    pr_number: int,
    request: PRActionRequest,
    db: Annotated[Any, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    重新触发指定 PR 的 CI

    需要登录用户权限
    """
    logger.info(f"CI rerun requested for PR #{pr_number} by user {current_user.username}")

    github_api = get_github_api_service()

    if not github_api.token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub token not configured",
        )

    # Get workflow runs for this PR
    logger.info(f"Fetching workflow runs for PR #{pr_number}...")
    workflow_runs = await github_api.get_workflow_runs_for_pr(pr_number)
    logger.info(f"Found {len(workflow_runs)} workflow runs")

    # Find failed workflow runs
    failed_runs = [run for run in workflow_runs if run.get("conclusion") == "failure"]

    if not failed_runs:
        # Check if any are in progress
        in_progress = [run for run in workflow_runs if run.get("status") == "in_progress"]
        if in_progress:
            return {
                "success": True,
                "message": f"CI is still running ({len(in_progress)} jobs in progress)",
                "pr_number": pr_number,
                "workflow_id": None,
            }
        return {
            "success": True,
            "message": f"No failed CI runs found for PR #{pr_number}",
            "pr_number": pr_number,
            "workflow_id": None,
        }

    # Rerun the first failed workflow run
    first_failed = failed_runs[0]
    workflow_run_id = first_failed.get("id")

    if not workflow_run_id:
        logger.error(f"Could not get workflow run ID for failed run")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not get workflow run ID",
        )

    logger.info(f"Rerunning workflow run {workflow_run_id} for PR #{pr_number}...")
    success = await github_api.rerun_workflow_run(workflow_run_id)

    if success:
        logger.info(f"✓ CI rerun triggered for PR #{pr_number} (workflow run {workflow_run_id})")
        return {
            "success": True,
            "message": f"CI rerun triggered for PR #{pr_number}",
            "pr_number": pr_number,
            "workflow_id": workflow_run_id,
        }
    else:
        logger.error(f"✗ Failed to trigger CI rerun for PR #{pr_number}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger CI rerun",
        )


@router.post("/pr/{pr_number}/force-merge")
async def force_merge_pr(
    pr_number: int,
    db: Annotated[Any, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_active_admin_user)]
):
    """
    强行合入指定 PR

    仅管理员权限，会记录合入操作到系统配置
    注意：vllm-ascend 仓库只支持 squash 方式合入
    """
    from sqlalchemy import select

    from app.models import ProjectDashboardConfig
    from datetime import UTC, datetime

    github_api = get_github_api_service()

    if not github_api.token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub token not configured",
        )

    # Get PR info
    pr_info = await github_api.get_pr(pr_number)
    if not pr_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PR #{pr_number} not found",
        )

    # Check if PR is mergeable
    if not pr_info.get("mergeable", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PR #{pr_number} has conflicts and cannot be merged",
        )

    # Use squash merge method (required for vllm-ascend repository)
    logger.info(f"Attempting to squash merge PR #{pr_number}...")
    result = await github_api.merge_pr(
        pr_number,
        merge_method="squash",
    )

    if result:
        merge_sha = result.get("sha")

        # Record the force merge action
        # 注意：记录操作必须成功，否则抛出异常回滚整个事务
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == "force_merge_records"
        )
        result_db = await db.execute(stmt)
        config = result_db.scalar_one_or_none()

        logger.warning(f"🔍 Force merge record config exists: {config is not None}")

        merge_record = {
            "pr_number": pr_number,
            "pr_title": pr_info.get("title"),
            "merged_by_user_id": current_user.id,
            "merged_by_username": current_user.username,
            "merged_at": datetime.now(UTC).isoformat(),
            "merge_sha": merge_sha,
            "merge_method": "squash",
        }

        logger.warning(f"📝 Merge record created: PR #{pr_number} by {current_user.username}")

        if config:
            # Append to existing records
            records = config.config_value.get("records", [])
            logger.warning(f"📊 Existing records count: {len(records)}")
            records.append(merge_record)
            # Keep only last 100 records
            records = records[-100:]
            config.config_value = {"records": records}
            config.description = "强行合入 PR 记录"
            # 显式标记 config_value 字段已修改，确保 SQLAlchemy 检测到变更
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(config, "config_value")
            logger.warning(f"📊 Updated records count: {len(records)}")
        else:
            # Create new config
            config = ProjectDashboardConfig(
                config_key="force_merge_records",
                config_value={"records": [merge_record]},
                description="强行合入 PR 记录",
            )
            db.add(config)
            logger.warning("🆕 Created new force_merge_records config")

        # 显式提交事务
        logger.warning(f"💾 Committing force merge record for PR #{pr_number}...")
        await db.commit()
        logger.warning(f"✅ Successfully recorded force merge for PR #{pr_number} by user {current_user.username}")

        return {
            "success": True,
            "message": f"PR #{pr_number} has been merged",
            "pr_number": pr_number,
            "merge_sha": merge_sha,
            "merge_method": "squash",
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to merge PR #{pr_number}",
        )


@router.get("/force-merge-records")
async def get_force_merge_records(
    db: Annotated[Any, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """
    获取强行合入 PR 的记录

    管理员可查看完整信息，普通用户只能查看记录列表
    """
    from sqlalchemy import select

    from app.models import ProjectDashboardConfig

    stmt = select(ProjectDashboardConfig).where(
        ProjectDashboardConfig.config_key == "force_merge_records"
    )
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        return {"records": []}

    records = config.config_value.get("records", [])
    
    # 按时间倒序排列（最新的在前）
    records.sort(key=lambda x: x.get("merged_at", ""), reverse=True)
    
    return {"records": records}


@router.post("/compare-tags")
async def compare_tags(
    request: TagComparisonRequest
):
    """
    比对两个 vllm-ascend tag

    显示两个版本之间合入的 commit 信息，按类别分类
    """
    # Ensure repo is cloned
    if not ensure_repo_cloned():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clone repository",
        )

    cache = get_github_cache()
    commits = cache.get_commits_between_tags(request.base_tag, request.head_tag)

    if commits is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to get commits between {request.base_tag} and {request.head_tag}",
        )

    # Categorize commits
    bug_fixes = [c for c in commits if c["category"] == "BugFix"]
    features = [c for c in commits if c["category"] == "Feature"]
    performance = [c for c in commits if c["category"] == "Performance"]
    refactor = [c for c in commits if c["category"] == "Refactor"]
    doc = [c for c in commits if c["category"] == "Doc"]
    test = [c for c in commits if c["category"] == "Test"]
    ci = [c for c in commits if c["category"] == "CI"]
    misc = [c for c in commits if c["category"] == "Misc"]

    summary = {
        "BugFix": len(bug_fixes),
        "Feature": len(features),
        "Performance": len(performance),
        "Refactor": len(refactor),
        "Doc": len(doc),
        "Test": len(test),
        "CI": len(ci),
        "Misc": len(misc),
    }

    return {
        "base_tag": request.base_tag,
        "head_tag": request.head_tag,
        "total_commits": len(commits),
        "commits": commits,
        "summary": summary,
        "bug_fixes": bug_fixes,
        "features": features,
        "performance_improvements": performance,
        "refactors": refactor,
        "docs": doc,
        "tests": test,
        "ci_changes": ci,
        "misc": misc,
    }


@router.get("/config")
async def get_dashboard_config(
    db: Annotated[Any, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_active_admin_user)]
):
    """
    获取项目看板所有配置

    仅管理员可访问
    """
    from sqlalchemy import select

    from app.models import ProjectDashboardConfig

    stmt = select(ProjectDashboardConfig)
    result = await db.execute(stmt)
    configs = result.scalars().all()

    return {
        "configs": [
            {
                "id": c.id,
                "config_key": c.config_key,
                "config_value": c.config_value,
                "description": c.description,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in configs
        ]
    }


@router.put("/config/{config_key}")
async def update_dashboard_config(
    config_key: str,
    update_data: ProjectDashboardConfigUpdate,
    db: Annotated[Any, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_active_admin_user)]
):
    """
    更新项目看板配置

    仅管理员可修改
    """
    from sqlalchemy import select

    from app.models import ProjectDashboardConfig

    stmt = select(ProjectDashboardConfig).where(
        ProjectDashboardConfig.config_key == config_key
    )
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration '{config_key}' not found",
        )

    try:
        config.config_value = update_data.config_value
        if update_data.description:
            config.description = update_data.description

        await db.commit()

        return {
            "success": True,
            "message": f"Configuration '{config_key}' updated",
            "config": {
                "id": config.id,
                "config_key": config.config_key,
                "config_value": config.config_value,
                "description": config.description,
            },
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}",
        )


@router.post("/cache/update")
async def update_local_cache(
    current_user: Annotated[User, Depends(get_current_active_admin_user)]
):
    """
    手动更新本地 git 仓库缓存

    仅管理员可操作
    """
    success = update_repo()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update local repository cache",
        )

    return {
        "success": True,
        "message": "Local repository cache updated successfully",
    }


@router.post("/cache/rebuild")
async def rebuild_local_cache(
    current_user: Annotated[User, Depends(get_current_active_admin_user)]
):
    """
    删除并重新克隆本地 git 仓库缓存

    用于修复损坏的缓存或获取完整的 git 历史

    仅管理员可操作
    """
    from app.services.github_cache import rebuild_repo

    success = rebuild_repo()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to rebuild local repository cache",
        )

    return {
        "success": True,
        "message": "Local repository cache rebuilt successfully. This may take several minutes.",
    }


@router.post("/github-cache/fix")
async def fix_github_cache(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fix local GitHub repository cache without full reclone

    This cleans up lock files, resets local changes, and fetches latest state.
    Much faster than rebuilding the entire repository.

    Admin only
    """
    from app.services.github_cache import fix_repo

    success = fix_repo()

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fix local repository cache",
        )

    return {
        "success": True,
        "message": "Local repository cache fixed successfully",
    }
