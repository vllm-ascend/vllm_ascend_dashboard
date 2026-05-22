"""
Upgrade script v0.0.5: Remove biweekly meeting configuration from database.

This script deletes all ProjectDashboardConfig records with config_key='biweekly_meeting'.
Run this script once after deploying the code changes that remove the biweekly meeting feature.

Usage:
    cd backend
    python scripts/upgrade_v0.0.5.py
"""

import asyncio
import logging
from sqlalchemy import select, delete
from app.db.session import AsyncSession
from app.models import ProjectDashboardConfig
from app.db.base import async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def remove_biweekly_meeting_config():
    """Remove all biweekly meeting configuration records from the database."""
    async with AsyncSession() as session:
        try:
            # Query existing biweekly meeting configs
            stmt = select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == "biweekly_meeting"
            )
            result = await session.execute(stmt)
            configs = result.scalars().all()

            if not configs:
                logger.info("No biweekly meeting configuration found. Nothing to delete.")
                return

            logger.info(f"Found {len(configs)} biweekly meeting configuration(s) to delete:")
            for config in configs:
                logger.info(f"  - ID: {config.id}, Description: {config.description}")

            # Delete all biweekly meeting configs
            delete_stmt = delete(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == "biweekly_meeting"
            )
            await session.execute(delete_stmt)
            await session.commit()

            logger.info(f"Successfully deleted {len(configs)} biweekly meeting configuration(s)")

        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to remove biweekly meeting configuration: {e}")
            raise


if __name__ == "__main__":
    logger.info("Starting biweekly meeting configuration cleanup...")
    asyncio.run(remove_biweekly_meeting_config())
    logger.info("Cleanup completed!")
