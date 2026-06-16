"""
Database upgrade script v0.0.12

Refactor alert_rules from single-condition to condition-group model:
- Create alert_condition_groups + alert_conditions tables
- Migrate existing rule data (1 rule → 1 group → 1 condition)
- Remove old condition columns from alert_rules and alert_history
- Add condition_details JSON to alert_history
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Refactor alert_rules to condition-group model (multi-condition support)"


async def check_table_exists(table_name: str) -> bool:
    try:
        def _get(conn):
            return inspect(conn).get_table_names()
        async with engine.begin() as conn:
            return table_name in await conn.run_sync(_get)
    except Exception:
        return False


async def check_column_exists(table_name: str, column_name: str) -> bool:
    try:
        def _get(conn):
            return [c["name"] for c in inspect(conn).get_columns(table_name)]
        async with engine.begin() as conn:
            return column_name in await conn.run_sync(_get)
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.12")
    print("=" * 60 + "\n")

    is_mysql = "mysql" in str(engine.url)

    # ── 1. Create alert_condition_groups ──
    if not await check_table_exists("alert_condition_groups"):
        if is_mysql:
            sql = """CREATE TABLE alert_condition_groups (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                rule_id INT NOT NULL,
                logic VARCHAR(10) NOT NULL DEFAULT 'AND',
                display_order INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX ix_alert_condition_groups_rule_id (rule_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        else:
            sql = """CREATE TABLE alert_condition_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL,
                logic VARCHAR(10) NOT NULL DEFAULT 'AND',
                display_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        async with SessionLocal() as db:
            await db.execute(text(sql))
            if not is_mysql:
                try:
                    await db.execute(text("CREATE INDEX ix_alert_condition_groups_rule_id ON alert_condition_groups(rule_id)"))
                except Exception:
                    pass
            await db.commit()
        print("  ✅ Created alert_condition_groups")
    else:
        print("  ✓ alert_condition_groups already exists")

    # ── 2. Create alert_conditions ──
    if not await check_table_exists("alert_conditions"):
        if is_mysql:
            sql = """CREATE TABLE alert_conditions (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                group_id INT NOT NULL,
                metric_field VARCHAR(50) NOT NULL,
                operator VARCHAR(10) NOT NULL,
                threshold DOUBLE NOT NULL,
                is_exclude BOOLEAN DEFAULT FALSE,
                display_order INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX ix_alert_conditions_group_id (group_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        else:
            sql = """CREATE TABLE alert_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                metric_field VARCHAR(50) NOT NULL,
                operator VARCHAR(10) NOT NULL,
                threshold REAL NOT NULL,
                is_exclude BOOLEAN DEFAULT 0,
                display_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        async with SessionLocal() as db:
            await db.execute(text(sql))
            if not is_mysql:
                try:
                    await db.execute(text("CREATE INDEX ix_alert_conditions_group_id ON alert_conditions(group_id)"))
                except Exception:
                    pass
            await db.commit()
        print("  ✅ Created alert_conditions")
    else:
        print("  ✓ alert_conditions already exists")

    # ── 3. Migrate existing rule data ──
    async with SessionLocal() as db:
        old_rows = (await db.execute(text("SELECT id, metric_field, operator, threshold FROM alert_rules"))).fetchall()
        migrated = 0
        for row in old_rows:
            rule_id, mf, oper, thresh = row[0], row[1], row[2], row[3]
            # Insert group
            result = await db.execute(
                text("INSERT INTO alert_condition_groups (rule_id, logic, display_order) VALUES (:rid, 'AND', 0)"),
                {"rid": rule_id},
            )
            group_id = result.lastrowid
            if not group_id and is_mysql:
                group_id = (await db.execute(text("SELECT LAST_INSERT_ID()"))).scalar()
            elif not group_id:
                group_id = (await db.execute(text("SELECT last_insert_rowid()"))).scalar()
            # Insert condition
            await db.execute(
                text("INSERT INTO alert_conditions (group_id, metric_field, operator, threshold, is_exclude, display_order) VALUES (:gid, :mf, :op, :th, 0, 0)"),
                {"gid": group_id, "mf": mf, "op": oper, "th": thresh},
            )
            migrated += 1
        if migrated > 0:
            await db.commit()
            print(f"  ✅ Migrated {migrated} existing alert rules to condition-group model")
        else:
            print("  ℹ️  No existing rules to migrate")

    # ── 4. Remove old columns from alert_rules ──
    for col in ["metric_field", "operator", "threshold"]:
        if await check_column_exists("alert_rules", col):
            async with SessionLocal() as db:
                await db.execute(text(f"ALTER TABLE alert_rules DROP COLUMN {col}"))
                await db.commit()
            print(f"  ✅ Dropped alert_rules.{col}")
        else:
            print(f"  ✓ alert_rules.{col} already removed")

    # ── 5. Remove old columns from alert_history ──
    for col in ["metric_field", "operator", "threshold"]:
        if await check_column_exists("alert_history", col):
            async with SessionLocal() as db:
                try:
                    await db.execute(text(f"ALTER TABLE alert_history DROP COLUMN {col}"))
                    await db.commit()
                    print(f"  ✅ Dropped alert_history.{col}")
                except Exception as e:
                    await db.rollback()
                    print(f"  ⚠ Could not drop alert_history.{col}: {e}")
        else:
            print(f"  ✓ alert_history.{col} already removed")

    # ── 6. Add condition_details to alert_history ──
    if not await check_column_exists("alert_history", "condition_details"):
        async with SessionLocal() as db:
            col_def = "JSON" if is_mysql else "TEXT"
            await db.execute(text(f"ALTER TABLE alert_history ADD COLUMN condition_details {col_def}"))
            await db.commit()
        print("  ✅ Added alert_history.condition_details")
    else:
        print("  ✓ alert_history.condition_details already exists")

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.12 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
