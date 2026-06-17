"""
每日总结 API 路由
"""
import logging
from datetime import datetime, timedelta, date as DateType, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_active_super_admin_user, get_db
from app.models import User
from app.schemas.daily_summary import (
    GenerateSummaryRequest, FetchDataRequest,
    DailySummaryResponse, DailySummaryListResponse, DailySummaryListItem,
    FetchDataResponse, GenerateSummaryResponse,
    TrendDataResponse, TrendDataItem,
)
from app.services.daily_summary import DailySummaryService
from app.services.daily_data_file_store import DailyDataFileStore

logger = logging.getLogger(__name__)


def format_datetime_utc(dt: datetime | None) -> str | None:
    """
    格式化 datetime 为 ISO 格式，确保带 UTC 时区标识
    
    如果 datetime 不带时区信息，假设为 UTC 时间并添加 +00:00 标识
    """
    if dt is None:
        return None
    
    # 如果 datetime 不带时区信息，假设为 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.isoformat()

router = APIRouter(prefix="/daily-summary", tags=["每日总结"])


@router.post("/generate", response_model=GenerateSummaryResponse)
async def generate_daily_summary(
    request_data: GenerateSummaryRequest,
    current_user: Annotated[User, Depends(get_current_active_super_admin_user)],
    db: AsyncSession = Depends(get_db)
):
    """
    手动触发生成每日总结

    需要超级管理员权限（super_admin）
    """
    try:
        # 解析日期
        if request_data.date:
            summary_date = DateType.fromisoformat(request_data.date)
        else:
            # 默认为昨天
            summary_date = DateType.today() - timedelta(days=1)

        # 验证日期不能是未来
        if summary_date > DateType.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="日期不能是未来时间"
            )

        service = DailySummaryService(db)
        result = await service.generate_summary(
            project=request_data.project,
            summary_date=summary_date,
            llm_provider=request_data.llm_provider,
            force_regenerate=request_data.force_regenerate,
        )

        return {
            "success": True,
            "message": "总结生成成功",
            "data": {
                "project": result.project,
                "date": result.date.isoformat(),
                "pr_count": result.pr_count,
                "issue_count": result.issue_count,
                "commit_count": result.commit_count,
                "generation_time_seconds": result.generation_time_seconds,
            }
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to generate daily summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成总结失败：{str(e)}"
        )


@router.post("/fetch-data", response_model=FetchDataResponse)
async def fetch_daily_data(
    request_data: FetchDataRequest,
    current_user: Annotated[User, Depends(get_current_active_super_admin_user)],
    db: AsyncSession = Depends(get_db)
):
    """
    手动触发采集每日数据

    需要超级管理员权限（super_admin）
    """
    try:
        fetch_date = DateType.fromisoformat(request_data.date)

        # 验证日期不能是未来
        if fetch_date > DateType.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="日期不能是未来时间"
            )

        service = DailySummaryService(db)
        result = await service.fetch_daily_data(
            project=request_data.project,
            fetch_date=fetch_date,
            force_refresh=request_data.force_refresh,
        )

        return {
            "success": True,
            "message": "数据采集成功" if not request_data.force_refresh else "数据已重新采集",
            "data": {
                "pr_count": len(result.prs),
                "issue_count": len(result.issues),
                "commit_count": len(result.commits),
            }
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to fetch daily data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"数据采集失败：{str(e)}"
        )


@router.post("/refresh-status", response_model=FetchDataResponse)
async def refresh_daily_status(
    request_data: FetchDataRequest,
    current_user: Annotated[User, Depends(get_current_active_super_admin_user)],
    db: AsyncSession = Depends(get_db)
):
    """
    刷新指定日期已采集数据的 PR 和 Issue 状态

    需要超级管理员权限（super_admin）

    仅更新已有 PR 和 Issue 的状态（如 open/closed/merged），不采集新数据
    """
    try:
        fetch_date = DateType.fromisoformat(request_data.date)

        # 验证日期不能是未来
        if fetch_date > DateType.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="日期不能是未来时间"
            )

        service = DailySummaryService(db)
        pr_count, issue_count = await service.refresh_pr_issue_status(
            project=request_data.project,
            fetch_date=fetch_date,
        )

        return {
            "success": True,
            "message": f"已刷新 {pr_count} 个 PR 和 {issue_count} 个 Issue 的状态",
            "data": {
                "pr_count": pr_count,
                "issue_count": issue_count,
                "commit_count": 0,
            }
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to refresh status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刷新状态失败：{str(e)}"
        )


@router.get("/{project}/list", response_model=DailySummaryListResponse)
async def list_daily_summaries(
    project: str,
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    获取每日总结列表

    所有登录用户可访问
    """
    try:
        file_store = DailyDataFileStore()
        # 从文件存储获取可用日期列表
        dates = await file_store.list_available_dates(project, limit=limit + offset)

        # 分页
        paginated_dates = dates[offset:offset + limit]

        # 获取每个日期的元数据
        data_list = []
        for date_str in paginated_dates:
            data_date = DateType.fromisoformat(date_str)
            summary_data = await file_store.load_summary(project, data_date)

            if summary_data:
                data_list.append(
                    DailySummaryListItem(
                        date=summary_data['data_date'],
                        project=summary_data['project'],
                        pr_count=summary_data.get('pr_count', 0),
                        issue_count=summary_data.get('issue_count', 0),
                        commit_count=summary_data.get('commit_count', 0),
                        has_data=summary_data.get('has_data', False),
                        generated_at=summary_data.get('generated_at'),
                    )
                )

        return {
            "total": len(dates),
            "data": data_list,
        }
    except Exception as e:
        logger.error(f"Failed to list daily summaries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取列表失败：{str(e)}"
        )


@router.post("/{project}/{date}/regenerate", response_model=GenerateSummaryResponse)
async def regenerate_daily_summary(
    project: str,
    date: str,
    current_user: Annotated[User, Depends(get_current_active_super_admin_user)],
    llm_provider: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    重新生成指定日期的每日总结

    需要超级管理员权限（super_admin）
    """
    try:
        summary_date = DateType.fromisoformat(date)

        service = DailySummaryService(db)
        result = await service.generate_summary(
            project=project,
            summary_date=summary_date,
            llm_provider=llm_provider,
            force_regenerate=True,
        )

        return {
            "success": True,
            "message": "总结重新生成成功",
            "data": {
                "project": result.project,
                "date": result.date.isoformat(),
                "pr_count": result.pr_count,
                "issue_count": result.issue_count,
                "commit_count": result.commit_count,
                "generation_time_seconds": result.generation_time_seconds,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to regenerate daily summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重新生成总结失败：{str(e)}"
        )


# ============ 每日数据获取 API ============

@router.get("/{project}/{date}/data")
async def get_daily_data(
    project: str,
    date: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """
    获取指定日期的每日数据（PR、Issue、Commit）

    所有登录用户可访问

    从文件存储中读取指定日期的项目动态数据
    """
    try:
        data_date = DateType.fromisoformat(date)
        file_store = DailyDataFileStore()

        # 从文件加载数据
        data = await file_store.load_daily_data(project, data_date)

        if not data:
            return {
                "project": project,
                "date": date,
                "pull_requests": [],
                "issues": [],
                "commits": [],
                "releases": {
                    "latest": None,
                    "prerelease": None,
                },
                "counts": {
                    "prs": 0,
                    "issues": 0,
                    "commits": 0,
                },
                "has_data": False,
                "fetched_at": None,
            }

        return {
            "project": project,
            "date": date,
            "pull_requests": data.get("pull_requests", []),
            "issues": data.get("issues", []),
            "commits": data.get("commits", []),
            "releases": {
                "latest": None,
                "prerelease": None,
            },
            "counts": data.get("counts", {
                "prs": len(data.get("pull_requests", [])),
                "issues": len(data.get("issues", [])),
                "commits": len(data.get("commits", [])),
            }),
            "has_data": data.get("counts", {}).get("prs", 0) > 0 or
                       data.get("counts", {}).get("issues", 0) > 0 or
                       data.get("counts", {}).get("commits", 0) > 0,
            "fetched_at": data.get("fetched_at"),
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"日期格式错误：{str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to get daily data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取每日数据失败：{str(e)}"
        )


@router.get("/{project}/available-dates")
async def get_available_dates(
    project: str,
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    获取项目可用日期列表

    返回文件存储中有数据的日期列表
    """
    try:
        file_store = DailyDataFileStore()
        dates = await file_store.list_available_dates(project, limit=limit)

        return {
            "project": project,
            "dates": dates,
            "total": len(dates),
        }
    except Exception as e:
        logger.error(f"Failed to get available dates: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取可用日期失败：{str(e)}"
        )


@router.get("/{project}/trend", response_model=TrendDataResponse)
async def get_trend_data(
    project: str,
    current_user: Annotated[User, Depends(get_current_user)],
    days: int = Query(7, ge=1, le=90),
):
    """
    获取项目社区趋势数据（PR/Issue/Commit 每日计数）

    所有登录用户可访问

    返回最近 N 天的 PR/Issue/Commit 每日数量趋势
    """
    try:
        file_store = DailyDataFileStore()
        available_dates = await file_store.list_available_dates(project, limit=days)

        trend_data = []
        for date_str in available_dates:
            data_date = DateType.fromisoformat(date_str)
            daily_data = await file_store.load_daily_data(project, data_date)

            if daily_data:
                counts = daily_data.get("counts", {})
                trend_data.append(TrendDataItem(
                    date=date_str,
                    pr_count=counts.get("prs", 0),
                    issue_count=counts.get("issues", 0),
                    commit_count=counts.get("commits", 0),
                ))
            else:
                summary_meta = await file_store.load_summary(project, data_date)
                if summary_meta:
                    trend_data.append(TrendDataItem(
                        date=date_str,
                        pr_count=summary_meta.get("pr_count", 0),
                        issue_count=summary_meta.get("issue_count", 0),
                        commit_count=summary_meta.get("commit_count", 0),
                    ))
                else:
                    trend_data.append(TrendDataItem(
                        date=date_str,
                        pr_count=0,
                        issue_count=0,
                        commit_count=0,
                    ))

        trend_data.sort(key=lambda x: x.date)

        return TrendDataResponse(
            project=project,
            days=days,
            data=trend_data,
        )
    except Exception as e:
        logger.error(f"Failed to get trend data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取趋势数据失败：{str(e)}"
        )


@router.get("/{project}/{date}", response_model=DailySummaryResponse)
async def get_daily_summary(
    project: str,
    date: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """
    获取指定日期的每日总结

    所有登录用户可访问

    如果总结尚未生成，返回空状态而不是 404
    """
    try:
        summary_date = DateType.fromisoformat(date)
        file_store = DailyDataFileStore()

        summary_data = await file_store.load_summary(project, summary_date)

        if not summary_data:
            return {
                "project": project,
                "date": date,
                "summary_markdown": "",
                "has_data": False,
                "pr_count": 0,
                "issue_count": 0,
                "commit_count": 0,
                "generated_at": None,
                "status": "not_generated",
            }

        return {
            "project": summary_data['project'],
            "date": summary_data['data_date'],
            "summary_markdown": summary_data['summary_markdown'],
            "has_data": summary_data.get('has_data', False),
            "pr_count": summary_data.get('pr_count', 0),
            "issue_count": summary_data.get('issue_count', 0),
            "commit_count": summary_data.get('commit_count', 0),
            "generated_at": summary_data.get('generated_at'),
            "status": summary_data.get('status', 'success'),
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"日期格式错误：{str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to get daily summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取总结失败：{str(e)}"
        )