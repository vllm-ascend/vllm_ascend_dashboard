"""
Database upgrade script v0.0.13

Extract SMTP fields from daily_report_config into standalone smtp_config key.
Both daily report and alert rules share smtp_config for sending emails.
"""
import asyncio
import logging

from sqlalchemy import select, text

from app.db.base import SessionLocal

logger = logging.getLogger(__name__)

DESCRIPTION = "Extract SMTP config to shared smtp_config key"

SMTP_FIELDS = {"smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_use_tls", "report_from_email"}
REPORT_ONLY_FIELDS = {"report_recipients", "report_cc_recipients", "report_subject_template"}


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.13")
    print("=" * 60 + "\n")

    from app.models import ProjectDashboardConfig

    async with SessionLocal() as db:
        stmt = select(ProjectDashboardConfig).where(ProjectDashboardConfig.config_key == "daily_report_config")
        result = await db.execute(stmt)
        report_config = result.scalar_one_or_none()

        if not report_config or not report_config.config_value:
            print("  ℹ️  No daily_report_config found, nothing to migrate")
            print("\n" + "=" * 60)
            print("  ✅ Upgrade to v0.0.13 completed (no data to migrate)!")
            print("=" * 60 + "\n")
            return

        old_config = dict(report_config.config_value)

        # Check if smtp_config already exists
        stmt2 = select(ProjectDashboardConfig).where(ProjectDashboardConfig.config_key == "smtp_config")
        result2 = await db.execute(stmt2)
        smtp_config = result2.scalar_one_or_none()

        if smtp_config:
            print("  ℹ️  smtp_config already exists, merging non-empty values")
            existing_smtp = dict(smtp_config.config_value)
        else:
            existing_smtp = {}

        # Extract SMTP fields + map report_from_email → from_email
        new_smtp = {}
        for key in SMTP_FIELDS:
            if key in old_config and old_config.get(key):
                new_smtp[key] = old_config[key]
        # Map report_from_email to from_email
        if "report_from_email" in new_smtp:
            new_smtp["from_email"] = new_smtp.pop("report_from_email")

        # Merge with existing
        merged_smtp = {**existing_smtp, **new_smtp}

        # Create report-only config
        new_report = {}
        for key in REPORT_ONLY_FIELDS:
            if key in old_config:
                new_report[key] = old_config[key]

        if smtp_config:
            smtp_config.config_value = merged_smtp
            print("  ✅ Updated existing smtp_config")
        else:
            smtp = ProjectDashboardConfig(config_key="smtp_config", config_value=merged_smtp, description="SMTP 邮件服务器配置")
            db.add(smtp)
            print("  ✅ Created smtp_config")

        report_config.config_value = new_report
        await db.commit()

        smtp_keys = [k for k in merged_smtp if merged_smtp[k]]
        report_keys = [k for k in new_report if new_report[k]]
        print(f"  SMTP fields extracted: {', '.join(smtp_keys) if smtp_keys else '(none set)'}")
        print(f"  Report fields retained: {', '.join(report_keys) if report_keys else '(none set)'}")

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.13 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
