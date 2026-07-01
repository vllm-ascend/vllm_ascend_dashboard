"""Database upgrade v0.0.24 - 模型看板增强：统一模型注册表 + 上游支持矩阵自动同步

创建 3 张新表：model_registry, model_feature_matrix, feature_compatibility
迁移数据：ModelConfig → ModelRegistry，ProjectDashboardConfig(model_support_matrix) → ModelFeatureMatrix
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect, text
from app.db.base import SessionLocal, engine
from app.models import Base

logger = logging.getLogger(__name__)
DESCRIPTION = "模型看板增强 - 统一模型注册表 + 上游支持矩阵自动同步"

NEW_TABLES = ["model_registry", "model_feature_matrix", "feature_compatibility"]

TOGGLE_FEATURES = [
    "chunked_prefill", "automatic_prefix_cache", "lora",
    "speculative_decoding", "async_scheduling", "tensor_parallel",
    "pipeline_parallel", "expert_parallel", "data_parallel",
    "prefilled_decode_disaggregation", "piecewise_aclgraph",
    "fullgraph_aclgraph", "mlp_weight_prefetch",
]


async def check_table_exists(table_name: str) -> bool:
    def _check(conn):
        return inspect(conn).has_table(table_name)
    try:
        async with engine.begin() as conn:
            return await conn.run_sync(_check)
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.24")
    print("  模型看板增强 - 统一模型注册表 + 上游支持矩阵自动同步")
    print("=" * 60 + "\n")

    # 1. 创建新表
    for table_name in NEW_TABLES:
        if await check_table_exists(table_name):
            print(f"  [OK] Table '{table_name}' already exists")
            continue
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn, tn=table_name: Base.metadata.tables[tn].create(sync_conn, checkfirst=True)
            )
        print(f"  [DONE] Created table '{table_name}'")

    # 2. 迁移数据：model_configs → model_registry
    async with SessionLocal() as db:
        result = await db.execute(text("SELECT count(*) FROM model_registry"))
        existing_count = result.scalar()
        if existing_count and existing_count > 0:
            print(f"  [OK] model_registry already has {existing_count} rows, skipping migration")
        else:
            result = await db.execute(text(
                "SELECT id, model_name, series, config_yaml, status, created_by, "
                "key_metrics_config, pass_threshold, startup_commands, official_doc_url "
                "FROM model_configs"
            ))
            rows = result.fetchall()
            migrated = 0
            for row in rows:
                await db.execute(text(
                    "INSERT INTO model_registry "
                    "(model_name, role, series, config_yaml, status, created_by, "
                    "key_metrics_config, pass_threshold, startup_commands, official_doc_url, "
                    "model_type, support_status, source, manual_overrides) "
                    "VALUES (:model_name, 'generative', :series, :config_yaml, :status, :created_by, "
                    ":key_metrics_config, :pass_threshold, :startup_commands, :official_doc_url, "
                    "'text_generative', 'untested', 'manual', '[]')"
                ), {
                    "model_name": row[1],
                    "series": row[2],
                    "config_yaml": row[3],
                    "status": row[4],
                    "created_by": row[5],
                    "key_metrics_config": row[6],
                    "pass_threshold": row[7],
                    "startup_commands": row[8],
                    "official_doc_url": row[9],
                })
                migrated += 1
            await db.commit()
            print(f"  [DONE] Migrated {migrated} rows from model_configs to model_registry")

    # 3. 迁移数据：ProjectDashboardConfig(model_support_matrix) → model_feature_matrix
    async with SessionLocal() as db:
        result = await db.execute(text(
            "SELECT config_value FROM project_dashboard_config WHERE config_key = 'model_support_matrix'"
        ))
        config_row = result.fetchone()
        if not config_row or not config_row[0]:
            print("  [OK] No model_support_matrix config found, skipping feature matrix migration")
        else:
            config_value = config_row[0]
            if isinstance(config_value, str):
                config_value = json.loads(config_value)
            entries = config_value.get("entries", []) if isinstance(config_value, dict) else []
            fm_count = 0
            for entry in entries:
                model_name = entry.get("model_name", "")
                if not model_name:
                    continue
                reg_result = await db.execute(text(
                    "SELECT id FROM model_registry WHERE model_name = :name AND role = 'generative'"
                ), {"name": model_name})
                reg_row = reg_result.fetchone()
                if not reg_row:
                    await db.execute(text(
                        "INSERT INTO model_registry (model_name, role, series, model_type, "
                        "support_status, source, manual_overrides) "
                        "VALUES (:name, 'generative', :series, 'text_generative', :support, 'manual', '[]')"
                    ), {
                        "name": model_name,
                        "series": entry.get("series", "Other"),
                        "support": entry.get("support", "untested"),
                    })
                    await db.commit()
                    reg_result = await db.execute(text(
                        "SELECT id FROM model_registry WHERE model_name = :name AND role = 'generative'"
                    ), {"name": model_name})
                    reg_row = reg_result.fetchone()

                if not reg_row:
                    continue
                registry_id = reg_row[0]

                await db.execute(text(
                    "UPDATE model_registry SET support_status = :status, "
                    "supported_hardware = :hw, weight_formats = :wf, "
                    "max_model_len = :mml, note = :note, official_doc_url = :doc "
                    "WHERE id = :id"
                ), {
                    "status": entry.get("support", "untested"),
                    "hw": json.dumps([h.strip() for h in entry["supported_hardware"].split("/")]) if entry.get("supported_hardware") else None,
                    "wf": json.dumps([w.strip() for w in entry["weight_format"].split("/")]) if entry.get("weight_format") else None,
                    "mml": str(entry.get("max_model_len")) if entry.get("max_model_len") else None,
                    "note": entry.get("note"),
                    "doc": entry.get("doc_link"),
                    "id": registry_id,
                })

                for feature_key in TOGGLE_FEATURES:
                    value = entry.get(feature_key)
                    if value is not None:
                        try:
                            await db.execute(text(
                                "INSERT INTO model_feature_matrix (model_id, feature_key, feature_status) "
                                "VALUES (:mid, :fk, :fs)"
                            ), {
                                "mid": registry_id,
                                "fk": feature_key,
                                "fs": "supported" if value else "not_supported",
                            })
                            fm_count += 1
                        except Exception:
                            pass

            await db.commit()
            print(f"  [DONE] Migrated {fm_count} feature matrix entries from model_support_matrix config")

    # 4. Fix #A: 给 model_reports 添加 model_registry_id 列并回填关联
    async with SessionLocal() as db:
        # 检查列是否已存在
        def _check_col(conn):
            from sqlalchemy import inspect as sa_inspect
            return [c['name'] for c in sa_inspect(conn).get_columns('model_reports')]
        existing_cols = await db.run_sync(_check_col)

        if 'model_registry_id' not in existing_cols:
            is_mysql = "mysql" in str(engine.url)
            col_type = "INTEGER NULL" if is_mysql else "INTEGER"
            await db.execute(text(f"ALTER TABLE model_reports ADD COLUMN model_registry_id {col_type}"))
            await db.commit()
            print("  [DONE] Added model_registry_id column to model_reports")
        else:
            print("  [OK] model_registry_id column already exists on model_reports")

        # 回填：model_reports.model_config_id → model_configs.model_name → model_registry.id
        result = await db.execute(text(
            "UPDATE model_reports SET model_registry_id = ("
            "  SELECT mr.id FROM model_registry mr "
            "  INNER JOIN model_configs mc ON mc.model_name = mr.model_name "
            "  WHERE mc.id = model_reports.model_config_id "
            "  AND mr.role = 'generative'"
            ") WHERE model_registry_id IS NULL"
        ))
        await db.commit()
        print(f"  [DONE] Backfilled model_registry_id for {result.rowcount} model_reports")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.24 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
