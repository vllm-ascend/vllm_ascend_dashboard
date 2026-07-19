"""
数据库版本化升级脚本
- 自动检测当前数据库版本
- 按顺序执行升级脚本
- 记录升级历史到 database_versions 表

使用方法:
    python scripts/upgrade_db.py              # 升级到最新版本
    python scripts/upgrade_db.py --target 0.0.1  # 升级到指定版本
    python scripts/upgrade_db.py --status   # 查看当前版本
"""
import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

# 添加父目录到路径以便导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

# 数据库版本表名
VERSION_TABLE = "database_versions"


async def check_table_exists(table_name: str) -> bool:
    """检查表是否存在（供升级脚本使用）"""
    try:
        def _get_table_names(conn):
            from sqlalchemy import inspect
            inspector = inspect(conn)
            return inspector.get_table_names()

        async with engine.begin() as conn:
            table_names = await conn.run_sync(_get_table_names)
            return table_name in table_names
    except Exception:
        return False


async def check_column_exists(table_name: str, column_name: str) -> bool:
    """检查列是否存在（供升级脚本使用）"""
    try:
        def _get_columns(conn):
            from sqlalchemy import inspect
            inspector = inspect(conn)
            return [col['name'] for col in inspector.get_columns(table_name)]

        async with engine.begin() as conn:
            columns = await conn.run_sync(_get_columns)
            return column_name in columns
    except Exception:
        return False


async def ensure_version_table():
    """创建版本记录表（如果不存在）"""
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (
        id INT PRIMARY KEY AUTO_INCREMENT,
        version VARCHAR(20) NOT NULL UNIQUE,
        applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        description TEXT
    )
    """

    async with engine.begin() as conn:
        await conn.execute(text(create_sql))
    print(f"  ✓ Version table '{VERSION_TABLE}' ready")


async def get_current_version() -> str:
    """获取当前数据库版本"""
    try:
        # 先检查版本表是否存在
        if not await check_table_exists(VERSION_TABLE):
            return "0.0.0"

        async with SessionLocal() as db:
            stmt = text(f"SELECT version FROM {VERSION_TABLE} ORDER BY id DESC LIMIT 1")
            result = await db.execute(stmt)
            row = result.fetchone()
            if row:
                return row[0]
    except Exception:
        pass
    return "0.0.0"


async def mark_version_applied(version: str, description: str = ""):
    """标记版本已应用"""
    # 表名是内部定义的，不会有 SQL 注入风险
    async with SessionLocal() as db:
        stmt = text(
            f"INSERT INTO {VERSION_TABLE} (version, description, applied_at) "
            "VALUES (:version, :description, :applied_at)"
        )
        # 使用数据库的 CURRENT_TIMESTAMP 而不是 Python 生成的时间
        await db.execute(stmt, {
            "version": version,
            "description": description,
            "applied_at": datetime.now()  # 使用本地时间
        })
        await db.commit()


def get_available_upgrades(current_version: str) -> list[tuple[str, Path]]:
    """
    获取可用的升级脚本列表
    返回：[(version, script_path), ...] 按版本号排序
    """
    scripts_dir = Path(__file__).parent
    upgrade_pattern = re.compile(r"upgrade_v(\d+\.\d+\.\d+)\.py")

    upgrades = []
    for script in scripts_dir.glob("upgrade_v*.py"):
        match = upgrade_pattern.match(script.name)
        if match:
            version = match.group(1)
            # 只添加比当前版本新的升级
            if version_compare(version, current_version) > 0:
                upgrades.append((version, script))

    # 按版本号排序
    upgrades.sort(key=lambda x: [int(p) for p in x[0].split(".")])
    return upgrades


def version_compare(v1: str, v2: str) -> int:
    """
    比较两个版本号
    返回：>0 如果 v1 > v2, <0 如果 v1 < v2, 0 如果相等
    """
    parts1 = [int(p) for p in v1.split(".")]
    parts2 = [int(p) for p in v2.split(".")]

    # 补齐长度
    max_len = max(len(parts1), len(parts2))
    parts1.extend([0] * (max_len - len(parts1)))
    parts2.extend([0] * (max_len - len(parts2)))

    for p1, p2 in zip(parts1, parts2, strict=False):
        if p1 > p2:
            return 1
        elif p1 < p2:
            return -1
    return 0


async def run_upgrade(version: str, script_path: Path) -> bool:
    """
    执行升级脚本
    返回：True 如果成功，False 如果失败
    """
    print(f"\n{'='*60}")
    print(f"  Upgrading to v{version}")
    print(f"  Script: {script_path.name}")
    print(f"{'='*60}\n")

    try:
        # 导入升级模块
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"upgrade_{version}", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 执行 upgrade 函数
        if hasattr(module, "upgrade"):
            await module.upgrade()

            # 记录版本
            description = getattr(module, "DESCRIPTION", f"Upgrade to v{version}")
            await mark_version_applied(version, description)

            print(f"\n  ✅ Successfully upgraded to v{version}")
            return True
        else:
            print(f"  ❌ Error: {script_path.name} does not have 'upgrade' function")
            return False

    except Exception as e:
        print(f"  ❌ Error upgrading to v{version}: {e}")
        return False


async def upgrade_database(target_version: str = None):
    """
    执行数据库升级
    """
    print("\n" + "="*60)
    print("  vLLM Ascend Dashboard - Database Upgrade")
    print("="*60 + "\n")

    # 确保版本表存在
    await ensure_version_table()

    # 获取当前版本
    current_version = await get_current_version()
    print(f"  Current version: v{current_version}")

    # 获取可用的升级
    upgrades = get_available_upgrades(current_version)

    if not upgrades:
        print("\n  ✓ Database is up to date")
        print("="*60 + "\n")
        return

    print(f"  Available upgrades: {len(upgrades)}")
    for version, _ in upgrades:
        print(f"    - v{version}")
    print()

    # 如果指定了目标版本，只升级到该版本
    if target_version:
        upgrades = [(v, p) for v, p in upgrades if version_compare(v, target_version) <= 0]
        if not upgrades:
            print(f"  ⚠️  Target version v{target_version} is not higher than current version")
            return

    # 执行升级
    success_count = 0
    for version, script_path in upgrades:
        if await run_upgrade(version, script_path):
            success_count += 1
        else:
            print(f"\n  ❌ Upgrade stopped at v{version}")
            print("  Please fix the issue and run again")
            break

    # 显示结果
    print("\n" + "="*60)
    if success_count == len(upgrades):
        print("  ✅ All upgrades completed successfully!")
    else:
        print(f"  ⚠️  Partially completed: {success_count}/{len(upgrades)} upgrades")

    new_version = await get_current_version()
    print(f"  Current version: v{new_version}")
    print("="*60 + "\n")


async def show_status():
    """显示数据库版本状态"""
    print("\n" + "="*60)
    print("  Database Version Status")
    print("="*60 + "\n")

    await ensure_version_table()

    try:
        async with SessionLocal() as db:
            stmt = text(f"SELECT version, applied_at, description FROM {VERSION_TABLE} ORDER BY id DESC")
            result = await db.execute(stmt)
            rows = result.fetchall()

            if rows:
                print("  Version History:")
                for i, (version, applied_at, description) in enumerate(rows):
                    marker = "→" if i == 0 else " "
                    print(f"    {marker} v{version} - {applied_at}")
                    if description:
                        print(f"      {description}")
            else:
                print("  No version records found")
    except Exception as e:
        print(f"  ⚠️  Error reading version history: {e}")

    print("\n" + "="*60 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="Database upgrade tool")
    parser.add_argument(
        "--target", "-t",
        type=str,
        help="Target version to upgrade to (e.g., 0.2.1)"
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show current version status"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available upgrades"
    )

    args = parser.parse_args()

    if args.status:
        await show_status()
    elif args.list:
        await ensure_version_table()
        current = await get_current_version()
        upgrades = get_available_upgrades(current)
        print(f"\nCurrent version: v{current}")
        print(f"Available upgrades: {len(upgrades)}")
        for version, path in upgrades:
            print(f"  - v{version} ({path.name})")
        print()
    else:
        await upgrade_database(args.target)


if __name__ == "__main__":
    asyncio.run(main())
