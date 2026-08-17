"""
数据库基类和会话管理
"""
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.core.config import settings

logger = logging.getLogger(__name__)

# MySQL 连接池配置
engine_kwargs = {
    "echo": False,
    "connect_args": {},
    "pool_size": settings.DB_POOL_SIZE,
    "max_overflow": settings.DB_MAX_OVERFLOW,
    "pool_timeout": settings.DB_POOL_TIMEOUT,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}
logger.info(
    "MySQL connection pooling enabled (pool_size=%s, max_overflow=%s, pool_timeout=%ss)",
    settings.DB_POOL_SIZE,
    settings.DB_MAX_OVERFLOW,
    settings.DB_POOL_TIMEOUT,
)

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)


@event.listens_for(engine.sync_engine, "connect")
def configure_mysql_session(dbapi_connection, connection_record):
    """Configure every MySQL connection with safe, UTC-based session defaults."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET time_zone = '+00:00'")
        cursor.execute("SET SESSION sort_buffer_size = 4 * 1024 * 1024")  # 4MB
        cursor.close()
        logger.debug("MySQL session timezone set to UTC and sort_buffer_size set to 4MB")
    except Exception as e:
        logger.warning(f"Failed to configure MySQL session: {e}")

logger.info("MySQL sessions will use UTC timezone and a 4MB sort buffer")

# 创建异步会话工厂
# 注意：autocommit=False 确保需要显式调用 commit()
# autoflush=False 避免自动刷新，手动控制事务
SessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的依赖注入函数"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database error: {e}")
        await db.rollback()
        raise
    finally:
        await db.close()
