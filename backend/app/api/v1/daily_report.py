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
from app.core.email import DEFAULT_SMTP_CONFIG, SMTP_CONFIG_KEY, get_smtp_config
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

# SMTP 相关的字段名
SMTP_FIELDS = {"smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_use_tls", "report_from_email", "from_email"}


async def _read_config(db, key: str) -> dict:
    stmt = select(ProjectDashboardConfig).where(ProjectDashboardConfig.config_key == key)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    return dict(config.config_value) if (config and config.config_value) else {}


async def _write_config(db, key: str, value: dict, description: str = ""):
    stmt = select(ProjectDashboardConfig).where(ProjectDashboardConfig.config_key == key)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config:
        config.config_value = value
    else:
        config = ProjectDashboardConfig(config_key=key, config_value=value, description=description)
        db.add(config)


@router.get("/config", response_model=DailyReportConfigResponse)
async def get_report_config(
    current_user: Annotated[User, Depends(get_current_active_admin_user)],
    db: AsyncSession = Depends(get_db),
):
    """获取报告邮件推送配置（admin 权限）"""
    smtp_config = await get_smtp_config(db)
    report_config = await _read_config(db, REPORT_CONFIG_KEY)

    return DailyReportConfigResponse(
        smtp_host=smtp_config.get("smtp_host", ""),
        smtp_port=smtp_config.get("smtp_port", 587),
        smtp_username=smtp_config.get("smtp_username", ""),
        smtp_use_tls=smtp_config.get("smtp_use_tls", True),
        smtp_password_set=bool(smtp_config.get("smtp_password", "")),
        report_from_email=smtp_config.get("from_email", ""),
        report_recipients=report_config.get("report_recipients", ""),
        report_cc_recipients=report_config.get("report_cc_recipients", ""),
        report_subject_template=report_config.get("report_subject_template", settings.REPORT_SUBJECT_TEMPLATE),
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
        smtp_config = await get_smtp_config(db)
        report_config = await _read_config(db, REPORT_CONFIG_KEY)

        updates = config_update.model_dump(exclude_none=True)

        # 字段名映射：report_from_email → from_email
        if "report_from_email" in updates:
            updates["from_email"] = updates.pop("report_from_email")

        # 拆分到 smtp_config 和 report_config
        for key, value in updates.items():
            if key == "smtp_password" and value:
                smtp_config["smtp_password"] = value
            elif key in SMTP_FIELDS:
                smtp_config[key] = value
            elif key in ("report_recipients", "report_cc_recipients", "report_subject_template"):
                report_config[key] = value

        await _write_config(db, SMTP_CONFIG_KEY, smtp_config, "SMTP 邮件服务器配置")
        await _write_config(db, REPORT_CONFIG_KEY, report_config, "每日运行报告配置")
        await db.commit()

        logger.info(f"Report/SMTP config updated by {current_user.username}: {list(updates.keys())}")

        return DailyReportConfigResponse(
            smtp_host=smtp_config.get("smtp_host", ""),
            smtp_port=smtp_config.get("smtp_port", 587),
            smtp_username=smtp_config.get("smtp_username", ""),
            smtp_use_tls=smtp_config.get("smtp_use_tls", True),
            smtp_password_set=bool(smtp_config.get("smtp_password", "")),
            report_from_email=smtp_config.get("from_email", ""),
            report_recipients=report_config.get("report_recipients", ""),
            report_cc_recipients=report_config.get("report_cc_recipients", ""),
            report_subject_template=report_config.get("report_subject_template", settings.REPORT_SUBJECT_TEMPLATE),
            report_enabled=settings.REPORT_ENABLED,
            report_schedule_hour=settings.REPORT_SCHEDULE_HOUR,
            report_schedule_minute=settings.REPORT_SCHEDULE_MINUTE,
        )
    except HTTPException:
        raise
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
        report_config = await _read_config(db, REPORT_CONFIG_KEY)
        smtp_config = await get_smtp_config(db)

        if not report_config.get("report_recipients"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请先配置收件人（在系统配置页面设置 report_recipients）",
            )
        if not smtp_config.get("smtp_host"):
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