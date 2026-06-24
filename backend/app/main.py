"""
vLLM Ascend Dashboard - Backend Application
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    alert_rules,
    auth,
    ci,
    commit_analysis,
    daily_report,
    daily_summary,
    issue_diagnosis,
    job_owners,
    model_sync_configs,
    models,
    performance,
    pr_pipeline,
    project_dashboard,
    resource_dashboard,
    resource_metrics,
    stats,
    system_config,
    users,
    workflows,
)
from app.core.config import settings
from app.db.base import engine
from app.middleware.usage_tracking import UsageTrackingMiddleware
from app.models import Base
from app.services.scheduler import get_scheduler, start_scheduler, stop_scheduler_async

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)

# 降低第三方库日志级别，避免打印无用信息
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
# 注意：apscheduler.scheduler 保持默认级别，以便记录调度器执行日志
# 如果 LOG_LEVEL=WARNING，调度器的 INFO 日志会被过滤，这是正常的

logger = logging.getLogger(__name__)


async def init_db():
    """初始化数据库表"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")

        await _migrate_email_column()

        # 初始化 LLM 提供商默认配置
        await _init_llm_provider_configs()

        # 同步 provider 配置到 LiteLLM 网关（生产环境）
        await _sync_litellm_providers()

        # Claude Code CLI 预热检查 —— 后台执行，不阻塞启动
        asyncio.create_task(_warmup_claude_code_cli())
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}", exc_info=True)
        raise


async def _migrate_email_column():
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            null_count = (await db.execute(text("SELECT COUNT(*) FROM users WHERE email IS NULL OR email = ''"))).scalar()
            if null_count:
                await db.execute(text("UPDATE users SET email = username || '@placeholder.local' WHERE email IS NULL OR email = ''"))
                await db.commit()
            try:
                await db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
                await db.commit()
            except Exception as idx_err:
                if "duplicate" in str(idx_err).lower() or "unique" in str(idx_err).lower():
                    await db.execute(text("UPDATE users SET email = email || '_' || id WHERE id NOT IN (SELECT MIN(id) FROM users WHERE email IS NOT NULL GROUP BY email) AND email IS NOT NULL"))
                    await db.commit()
                    await db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
                    await db.commit()
    except Exception as e:
        logger.warning(f"Email migration skipped (non-fatal): {e}")


async def _warmup_claude_code_cli():
    """Claude Code CLI 预热：验证 CLI 可用 + API key 有效"""
    try:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.models.daily_summary import LLMProviderConfig
        from app.services.claude_code_cli import ClaudeCodeCLI

        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            stmt = select(LLMProviderConfig).where(LLMProviderConfig.is_active == True).limit(1)
            result = await db.execute(stmt)
            config = result.scalar_one_or_none()

        if not config or not config.api_key:
            logger.warning("No active LLM provider configured, skipping CLI warmup")
            return

        cli = ClaudeCodeCLI()
        ok = await cli.ensure_initialized({
            "provider": config.provider,
            "api_key": config.api_key,
            "api_base_url": config.api_base_url or "",
            "default_model": config.default_model,
        })

        if ok:
            logger.info("Claude Code CLI warmup successful")
        else:
            logger.warning("Claude Code CLI warmup failed — analysis will fallback to direct API")
    except Exception as e:
        logger.warning("Claude Code CLI warmup error (non-fatal): %s", e)


async def _sync_litellm_providers():
    """同步启用的 LLM provider 到 LiteLLM 网关"""
    try:
        from app.services.litellm_sync import get_litellm_sync
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        sync = get_litellm_sync()
        if not sync.available:
            logger.info("LiteLLM not configured (LITELLM_PROXY_URL not set), skipping sync")
            return

        # 直接写配置文件，不依赖 health check
        # LiteLLM 可能还没就绪，但文件写入后下次启动就会读取
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            count = await sync.sync_from_db(db)
            logger.info(f"Synced {count} providers to LiteLLM")
    except Exception as e:
        logger.warning(f"LiteLLM provider sync failed (non-fatal): {e}")


async def _init_llm_provider_configs():
    """初始化 LLM 提供商默认配置"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.models.daily_summary import LLMProviderConfig

    # 创建临时会话
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        try:
            # 检查是否已有配置
            stmt = select(LLMProviderConfig)
            result = await db.execute(stmt)
            existing = result.scalars().first()

            if existing:
                logger.info("LLM provider configs already exist, skipping initialization")
                return

            # 添加默认配置
            default_configs = [
                LLMProviderConfig(
                    provider='openai',
                    display_name='OpenAI API',
                    api_base_url='https://api.openai.com/v1',
                    default_model='gpt-4o',
                    enabled=True,
                    is_active=False,
                    display_order=1,
                ),
                LLMProviderConfig(
                    provider='anthropic',
                    display_name='Anthropic Claude',
                    api_base_url='https://api.anthropic.com',
                    default_model='claude-sonnet-4-20250514',
                    enabled=True,
                    is_active=False,
                    display_order=2,
                ),
                LLMProviderConfig(
                    provider='qwen',
                    display_name='通义千问',
                    api_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
                    default_model='qwen-plus',
                    enabled=True,
                    is_active=False,
                    display_order=3,
                ),
            ]

            for config in default_configs:
                db.add(config)

            await db.commit()
            logger.info("LLM provider configs initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize LLM provider configs: {e}", exc_info=True)
            await db.rollback()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting vLLM Ascend Dashboard application...")

    # 启动时初始化数据库
    await init_db()

    # 启动数据同步调度器
    try:
        start_scheduler()  # 调用 scheduler.start() 来添加任务并启动
        scheduler = get_scheduler()
        logger.info("Scheduler started successfully")
        logger.info(f"Scheduler running: {scheduler.scheduler.running}")
        # 记录已调度的任务
        for job in scheduler.scheduler.get_jobs():
            logger.info(f"Scheduled job: {job.id} - {job.name}, next run: {job.next_run_time}")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}", exc_info=True)

    yield

    # 关闭时清理资源
    logger.info("Shutting down application...")

    try:
        await stop_scheduler_async()
        logger.info("Scheduler stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}", exc_info=True)

    try:
        await engine.dispose()
        logger.info("Database engine disposed successfully")
    except Exception as e:
        logger.error(f"Error disposing database engine: {e}", exc_info=True)


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""

    app = FastAPI(
        title="vLLM Ascend Dashboard API",
        description="vLLM Ascend 社区看板后端 API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(UsageTrackingMiddleware)

    # 注册路由
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
    app.include_router(ci.router, prefix="/api/v1/ci", tags=["CI 数据"])
    app.include_router(commit_analysis.router, prefix="/api/v1/commit-analysis", tags=["Commit 分析"])
    app.include_router(daily_summary.router, prefix="/api/v1", tags=["每日总结"])
    app.include_router(models.router, prefix="/api/v1/models", tags=["模型管理"])
    app.include_router(model_sync_configs.router, prefix="/api/v1/model-sync-configs", tags=["模型同步配置"])
    app.include_router(performance.router, prefix="/api/v1/performance", tags=["性能数据"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["用户管理"])
    app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["Workflow 配置"])
    app.include_router(job_owners.router, prefix="/api/v1/job-owners", tags=["Job 责任人"])
    app.include_router(system_config.router, prefix="/api/v1/system/config", tags=["系统配置"])
    app.include_router(project_dashboard.router, prefix="/api/v1/project-dashboard", tags=["项目看板"])
    app.include_router(resource_dashboard.router, prefix="/api/v1/resource-dashboard", tags=["资源看板"])
    app.include_router(resource_metrics.router, prefix="/api/v1/resource-dashboard", tags=["资源看板"])
    app.include_router(daily_report.router, prefix="/api/v1", tags=["每日运行报告"])
    app.include_router(stats.router, prefix="/api/v1/stats", tags=["统计信息"])
    app.include_router(issue_diagnosis.router, prefix="/api/v1/issue-diagnosis", tags=["问题定位"])
    app.include_router(alert_rules.router, prefix="/api/v1", tags=["告警规则"])
    app.include_router(pr_pipeline.router, prefix="/api/v1/pr-pipeline", tags=["PR 流水线"])

    @app.get("/health")
    async def health_check():
        """健康检查接口"""
        return {
            "status": "healthy",
            "version": "0.1.0",
            "environment": settings.ENVIRONMENT,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
