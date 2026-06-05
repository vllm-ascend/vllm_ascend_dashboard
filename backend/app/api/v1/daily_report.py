"""
每日运行报告 API 路由
"""
import logging
from datetime import date as DateType, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_admin_user, get_current_active_super_admin_user, get_current_user, get_db
from app.core.config import settings
from app.models import ProjectDashboardConfig, User
from app.schemas.daily_report import (
    DailyReportConfigResponse,
    DailyReportConfigUpdate,
    DailyReportHistoryResponse,
    DailyReportHistoryListResponse,
    DailyReportTriggerResponse,
)
from app.services.daily_report import DailyReportService

logger = logging.getLogger(__name__)

REPORT_CONFIG_KEY = "daily_report_config"

router = APIRouter(prefix="/daily-report", tags=["每日运行报告"])


@router.get("/config", response_model=DailyReportConfigResponse)
async def get_report_config(
    current_user: Annotated[User, Depends(get_current_active_admin_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取报告邮件推送配置（admin 权限）"""
    stmt = select(ProjectDashboardConfig).where(
        ProjectDashboardConfig.config_key == REPORT_CONFIG_KEY
    )
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    db_config = config.config_value if config else {}

    return DailyReportConfigResponse(
        smtp_host=db_config.get("smtp_host", ""),
        smtp_port=db_config.get("smtp_port", 587),
        smtp_username=db_config.get("smtp_username", ""),
        smtp_use_tls=db_config.get("smtp_use_tls", True),
        smtp_password_set=bool(db_config.get("smtp_password", "")),
        report_from_email=db_config.get("report_from_email", ""),
        report_recipients=db_config.get("report_recipients", ""),
        report_cc_recipients=db_config.get("report_cc_recipients", ""),
        report_subject_template=db_config.get("report_subject_template", settings.REPORT_SUBJECT_TEMPLATE),
        report_enabled=settings.REPORT_ENABLED,
        report_schedule_hour=settings.REPORT_SCHEDULE_HOUR,
        report_schedule_minute=settings.REPORT_SCHEDULE_MINUTE,
    )


@router.put("/config", response_model=DailyReportConfigResponse)
async def update_report_config(
    config_update: DailyReportConfigUpdate,
    current_user: Annotated[User, Depends(get_current_active_super_admin_user)],
    db: AsyncSession = Depends(get_db),
):
    """更新报告邮件推送配置（super_admin 权限）"""
    try:
        service = DailyReportService(db)

        existing_config = await service._get_report_config()
        updates = config_update.model_dump(exclude_none=True)

        for key, value in updates.items():
            if key == "smtp_password" and value:
                existing_config["smtp_password"] = value
            elif key != "smtp_password":
                existing_config[key] = value

        await service._update_report_config(existing_config)
        await db.commit()

        logger.info(f"Report config updated by {current_user.username}: {list(updates.keys())}")

        return DailyReportConfigResponse(
            smtp_host=existing_config.get("smtp_host", ""),
            smtp_port=existing_config.get("smtp_port", 587),
            smtp_username=existing_config.get("smtp_username", ""),
            smtp_use_tls=existing_config.get("smtp_use_tls", True),
            smtp_password_set=bool(existing_config.get("smtp_password", "")),
            report_from_email=existing_config.get("report_from_email", ""),
            report_recipients=existing_config.get("report_recipients", ""),
            report_cc_recipients=existing_config.get("report_cc_recipients", ""),
            report_subject_template=existing_config.get("report_subject_template", settings.REPORT_SUBJECT_TEMPLATE),
            report_enabled=settings.REPORT_ENABLED,
            report_schedule_hour=settings.REPORT_SCHEDULE_HOUR,
            report_schedule_minute=settings.REPORT_SCHEDULE_MINUTE,
        )
    except Exception as e:
        logger.error(f"Failed to update report config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新配置失败：{str(e)}"
        )


@router.post("/trigger", response_model=DailyReportTriggerResponse)
async def trigger_report(
    current_user: Annotated[User, Depends(get_current_active_super_admin_user)],
    db: AsyncSession = Depends(get_db),
    report_date: Optional[str] = Query(None, description="报告日期，默认为昨天，格式 YYYY-MM-DD"),
):
    """手动触发一次报告生成和发送（super_admin 权限）"""
    try:
        service = DailyReportService(db)
        report_config = await service._get_report_config()

        if not report_config.get("report_recipients"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请先配置收件人（在系统配置页面设置 report_recipients）",
            )
        if not report_config.get("smtp_host"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请先配置 SMTP 服务器（在系统配置页面设置 smtp_host）",
            )

        if report_date:
            target_date = DateType.fromisoformat(report_date)
        else:
            target_date = DateType.today() - timedelta(days=1)

        if target_date > DateType.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="报告日期不能是未来时间",
            )

        history = await service.send_report(target_date)

        return DailyReportTriggerResponse(
            success=history.status == "sent",
            message="报告发送成功" if history.status == "sent" else f"报告发送失败：{history.error_message}",
            report_date=history.report_date,
            report_id=history.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"触发报告失败：{str(e)}"
        )


@router.get("/history", response_model=DailyReportHistoryListResponse)
async def get_report_history(
    current_user: Annotated[User, Depends(get_current_active_admin_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """查询报告发送历史（admin 权限，支持分页）"""
    try:
        service = DailyReportService(db)
        items, total = await service.get_report_history(limit=limit, offset=offset)

        return DailyReportHistoryListResponse(
            total=total,
            items=[DailyReportHistoryResponse.model_validate(item) for item in items],
        )
    except Exception as e:
        logger.error(f"Failed to get report history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史失败：{str(e)}"
        )


@router.get("/latest")
async def get_latest_report(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取最近一次报告内容（所有登录用户可访问）"""
    try:
        service = DailyReportService(db)
        latest = await service.get_latest_report()

        if not latest:
            return {"message": "暂无报告记录", "data": None}

        return {
            "id": latest.id,
            "report_date": latest.report_date,
            "subject": latest.subject,
            "status": latest.status,
            "sent_at": latest.sent_at.isoformat() if latest.sent_at else None,
            "ci_summary": latest.ci_summary,
            "model_summary": latest.model_summary,
            "github_summary": latest.github_summary,
            "performance_summary": latest.performance_summary,
        }
    except Exception as e:
        logger.error(f"Failed to get latest report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取最新报告失败：{str(e)}"
        )