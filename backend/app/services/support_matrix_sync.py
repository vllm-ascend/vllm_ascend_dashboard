"""
上游支持矩阵同步服务

从 vllm-ascend 仓库本地 clone（github_cache.py 管理）读取 Markdown 文件，
解析后增量更新数据库。支持 dry-run 模式和 manual_overrides 字段保护。
"""
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    FeatureCompatibility,
    ModelFeatureMatrix,
    ModelRegistry,
    ProjectDashboardConfig,
)
from app.services.github_cache import get_github_cache
from app.services.support_matrix_parser import (
    parse_feature_compatibility,
    parse_supported_features,
    parse_supported_models,
)

logger = logging.getLogger(__name__)

SYNC_STATUS_KEY = "support_matrix_sync_status"
GLOBAL_FEATURES_KEY = "support_matrix_global_features"

UPSTREAM_FIELDS = [
    "display_name", "model_type", "tier", "support_status",
    "weight_formats", "supported_hardware", "max_model_len",
    "upstream_issue", "official_doc_url",
]


async def sync_support_matrix(
    db: AsyncSession, dry_run: bool = False
) -> dict[str, Any]:
    """主同步入口：从本地 clone 读取 Markdown，解析后增量更新数据库

    Args:
        db: 异步数据库会话
        dry_run: True 时只返回 diff 不落库

    Returns:
        同步结果 dict
    """
    try:
        github_cache = get_github_cache()
        repo_dir = github_cache.cache_dir

        models_path = repo_dir / settings.SUPPORT_MATRIX_MODELS_PATH
        features_path = repo_dir / settings.SUPPORT_MATRIX_FEATURES_PATH
        compat_path = repo_dir / settings.SUPPORT_MATRIX_COMPAT_PATH

        if not models_path.exists():
            msg = f"supported_models.md not found in local clone: {models_path}"
            logger.error(msg)
            await _record_sync_status(db, success=False, error=msg, dry_run=dry_run)
            return {"success": False, "error": msg}

        models_content = models_path.read_text(encoding="utf-8")
        features_content = features_path.read_text(encoding="utf-8") if features_path.exists() else ""
        compat_content = compat_path.read_text(encoding="utf-8") if compat_path.exists() else ""

        upstream_models = parse_supported_models(models_content)
        upstream_features = parse_supported_features(features_content)
        upstream_compat = parse_feature_compatibility(compat_content)

        new_models: list[dict] = []
        updated_models: list[dict] = []

        for model_data in upstream_models:
            role = model_data.get("role", "generative")
            existing = (
                await db.execute(
                    select(ModelRegistry).where(
                        ModelRegistry.model_name == model_data["model_name"],
                        ModelRegistry.role == role,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                changed = _merge_upstream_data(existing, model_data)
                if changed:
                    updated_models.append({
                        "model_name": model_data["model_name"],
                        "role": role,
                        "changed_fields": changed,
                    })
                if not dry_run:
                    await _update_feature_matrix(db, existing.id, model_data.get("features", {}))
            else:
                new_models.append({
                    "model_name": model_data["model_name"],
                    "role": role,
                    "model_type": model_data.get("model_type"),
                    "tier": model_data.get("tier"),
                    "support_status": model_data.get("support_status"),
                })
                if not dry_run:
                    features = model_data.pop("features", {})
                    new_model = ModelRegistry(**model_data, source="upstream_sync")
                    new_model.upstream_synced_at = datetime.now(UTC)
                    db.add(new_model)
                    await db.flush()
                    await _update_feature_matrix(db, new_model.id, features)

        if not dry_run and upstream_compat:
            await _sync_feature_compatibility(db, upstream_compat)

        if not dry_run and upstream_features:
            await _save_global_features(db, upstream_features)

        result = {
            "success": True,
            "dry_run": dry_run,
            "models_synced": len(upstream_models),
            "new_models": new_models,
            "updated_models": updated_models,
            "features_synced": len(upstream_features),
            "compat_pairs_synced": len(upstream_compat),
        }

        if not dry_run:
            await _record_sync_status(db, success=True, **result)
            await db.commit()

        logger.info(
            f"Support matrix sync: {len(upstream_models)} models, "
            f"{len(new_models)} new, {len(updated_models)} updated, "
            f"{len(upstream_compat)} compat pairs"
        )
        return result

    except Exception as e:
        logger.error(f"Support matrix sync failed: {e}", exc_info=True)
        if not dry_run:
            await _record_sync_status(db, success=False, error=str(e))
            try:
                await db.commit()
            except Exception:
                await db.rollback()
        return {"success": False, "error": str(e)}


def _merge_upstream_data(existing: ModelRegistry, upstream: dict) -> list[str]:
    """增量合并：上游字段覆盖，跳过 manual_overrides 锁定的字段

    返回被修改的字段名列表。
    """
    locked = set(existing.manual_overrides or [])
    changed: list[str] = []

    for field in UPSTREAM_FIELDS:
        if field in locked:
            continue
        upstream_value = upstream.get(field)
        current_value = getattr(existing, field, None)
        if upstream_value is not None and upstream_value != current_value:
            setattr(existing, field, upstream_value)
            changed.append(field)

    existing.source = "upstream_sync"
    existing.upstream_synced_at = datetime.now(UTC)
    return changed


async def _update_feature_matrix(
    db: AsyncSession, registry_id: int, features: dict[str, str]
) -> None:
    """更新模型特性矩阵，保留 verified_by_report"""
    for feature_key, feature_status in features.items():
        fm = (
            await db.execute(
                select(ModelFeatureMatrix).where(
                    ModelFeatureMatrix.model_id == registry_id,
                    ModelFeatureMatrix.feature_key == feature_key,
                )
            )
        ).scalar_one_or_none()

        if fm:
            fm.feature_status = feature_status
        else:
            fm = ModelFeatureMatrix(
                model_id=registry_id,
                feature_key=feature_key,
                feature_status=feature_status,
            )
            db.add(fm)


async def _sync_feature_compatibility(
    db: AsyncSession, compat_data: list[dict]
) -> None:
    """同步特性互操作矩阵"""
    now = datetime.now(UTC)
    for item in compat_data:
        existing = (
            await db.execute(
                select(FeatureCompatibility).where(
                    FeatureCompatibility.feature_a == item["feature_a"],
                    FeatureCompatibility.feature_b == item["feature_b"],
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.compatibility = item["compatibility"]
            existing.footnote = item.get("footnote")
            existing.synced_at = now
        else:
            fc = FeatureCompatibility(
                feature_a=item["feature_a"],
                feature_b=item["feature_b"],
                compatibility=item["compatibility"],
                footnote=item.get("footnote"),
                synced_at=now,
            )
            db.add(fc)


async def _save_global_features(
    db: AsyncSession, features: list[dict]
) -> None:
    """保存全局功能支持状态到 ProjectDashboardConfig"""
    config = (
        await db.execute(
            select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == GLOBAL_FEATURES_KEY
            )
        )
    ).scalar_one_or_none()

    if config:
        config.config_value = {"features": features, "updated_at": datetime.now(UTC).isoformat()}
    else:
        config = ProjectDashboardConfig(
            config_key=GLOBAL_FEATURES_KEY,
            config_value={"features": features, "updated_at": datetime.now(UTC).isoformat()},
            description="全局功能支持状态（来自 supported_features.md）",
        )
        db.add(config)


async def _record_sync_status(
    db: AsyncSession, success: bool, dry_run: bool = False, **kwargs
) -> None:
    """将同步状态写入 ProjectDashboardConfig，供前端读取"""
    status = {
        "last_sync_at": datetime.now(UTC).isoformat(),
        "success": success,
        "dry_run": dry_run,
        **kwargs,
    }

    config = (
        await db.execute(
            select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == SYNC_STATUS_KEY
            )
        )
    ).scalar_one_or_none()

    if config:
        config.config_value = status
    else:
        config = ProjectDashboardConfig(
            config_key=SYNC_STATUS_KEY,
            config_value=status,
            description="支持矩阵同步状态",
        )
        db.add(config)


async def get_sync_status(db: AsyncSession) -> dict[str, Any]:
    """获取最近同步状态"""
    config = (
        await db.execute(
            select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == SYNC_STATUS_KEY
            )
        )
    ).scalar_one_or_none()

    if config and config.config_value:
        return config.config_value
    return {"last_sync_at": None, "success": None}


async def get_global_features(db: AsyncSession) -> dict[str, Any]:
    """获取全局功能支持状态"""
    config = (
        await db.execute(
            select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == GLOBAL_FEATURES_KEY
            )
        )
    ).scalar_one_or_none()

    if config and config.config_value:
        return config.config_value
    return {"features": [], "updated_at": None}


async def get_support_matrix(
    db: AsyncSession,
    model_type: str | None = None,
    role: str | None = None,
    series: str | None = None,
    support_status: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """获取完整支持矩阵（模型×特性交叉表）"""
    query = select(ModelRegistry).where(ModelRegistry.status == "active")
    if model_type:
        query = query.where(ModelRegistry.model_type == model_type)
    if role:
        query = query.where(ModelRegistry.role == role)
    if series:
        query = query.where(ModelRegistry.series == series)
    if support_status:
        query = query.where(ModelRegistry.support_status == support_status)
    if tier:
        query = query.where(ModelRegistry.tier == tier)

    registries = (await db.execute(query)).scalars().all()

    feature_columns = [
        {"key": k, "title": v}
        for k, v in [
            ("chunked_prefill", "Chunked Prefill"),
            ("automatic_prefix_cache", "APC"),
            ("lora", "LoRA"),
            ("speculative_decoding", "Spec Dec"),
            ("async_scheduling", "Async Sched"),
            ("tensor_parallel", "TP"),
            ("pipeline_parallel", "PP"),
            ("expert_parallel", "EP"),
            ("data_parallel", "DP"),
            ("prefilled_decode_disaggregation", "PD 分离"),
            ("piecewise_aclgraph", "Piecewise Graph"),
            ("fullgraph_aclgraph", "Full Graph"),
            ("mlp_weight_prefetch", "MLP Prefetch"),
        ]
    ]

    models_list = []
    for reg in registries:
        features_dict: dict[str, str] = {}
        verified_dict: dict[str, bool] = {}
        if reg.feature_matrix:
            for fm in reg.feature_matrix:
                features_dict[fm.feature_key] = fm.feature_status
                verified_dict[fm.feature_key] = fm.verified_by_report

        models_list.append({
            "id": reg.id,
            "model_name": reg.model_name,
            "display_name": reg.display_name,
            "series": reg.series,
            "model_type": reg.model_type,
            "role": reg.role,
            "tier": reg.tier,
            "support_status": reg.support_status,
            "weight_formats": reg.weight_formats,
            "supported_hardware": reg.supported_hardware,
            "max_model_len": reg.max_model_len,
            "official_doc_url": reg.official_doc_url,
            "note": reg.note,
            "features": features_dict,
            "verified_features": verified_dict,
            "source": reg.source,
            "upstream_synced_at": reg.upstream_synced_at.isoformat() if reg.upstream_synced_at else None,
        })

    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for m in models_list:
        by_type[m["model_type"]] = by_type.get(m["model_type"], 0) + 1
        by_status[m["support_status"]] = by_status.get(m["support_status"], 0) + 1
        by_tier[m.get("tier") or "unknown"] = by_tier.get(m.get("tier") or "unknown", 0) + 1

    return {
        "models": models_list,
        "feature_columns": feature_columns,
        "statistics": {
            "total_models": len(models_list),
            "by_type": by_type,
            "by_status": by_status,
            "by_tier": by_tier,
        },
    }


async def get_feature_compatibility(db: AsyncSession) -> dict[str, Any]:
    """获取特性互操作矩阵"""
    entries = (
        await db.execute(select(FeatureCompatibility))
    ).scalars().all()

    features_set: list[str] = []
    seen: set[str] = set()
    for e in entries:
        if e.feature_a not in seen:
            features_set.append(e.feature_a)
            seen.add(e.feature_a)
        if e.feature_b not in seen:
            features_set.append(e.feature_b)
            seen.add(e.feature_b)

    matrix = [
        {
            "feature_a": e.feature_a,
            "feature_b": e.feature_b,
            "compatibility": e.compatibility,
            "footnote": e.footnote,
        }
        for e in entries
    ]

    synced_at = max((e.synced_at for e in entries if e.synced_at), default=None)

    return {
        "features": features_set,
        "matrix": matrix,
        "legend": {
            "full": "✅ Full compatibility",
            "partial": "🟠 Partial compatibility",
            "none": "❌ No compatibility",
            "unknown": "❔ Unknown or TBD",
        },
        "synced_at": synced_at.isoformat() if synced_at else None,
    }
