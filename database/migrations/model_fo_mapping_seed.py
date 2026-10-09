"""Synchronize the versioned model-to-FO seed file into its runtime table."""
from __future__ import annotations

import logging

from sqlalchemy import text

from infrastructure.db.base import SessionLocal
from tooling.model_fo_mapping import normalize_model_key
from tooling.parsers.nightly_config_parser import load_model_fo_map

logger = logging.getLogger("model_fo_mapping_seed_migration")
MIGRATION_VERSION = "20261009_02_model_fo_mapping_seed"


async def run() -> dict[str, int | str]:
    """Upsert file-owned mappings without deleting runtime-only entries.

    The JSON file is the source of truth for its own keys.  Existing Nightly
    snapshots are intentionally untouched; they retain their materialized FO.
    """
    mappings = {
        normalize_model_key(model_path): model_fo.strip()
        for model_path, model_fo in load_model_fo_map().items()
        if normalize_model_key(model_path) and isinstance(model_fo, str) and model_fo.strip()
    }
    async with SessionLocal() as db:
        for model_key, model_fo in mappings.items():
            await db.execute(
                text("""
                    INSERT INTO model_fo_mappings (model_key, model_fo, created_at, updated_at)
                    VALUES (:model_key, :model_fo, UTC_TIMESTAMP(), UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE
                      model_fo = VALUES(model_fo),
                      updated_at = UTC_TIMESTAMP()
                """),
                {"model_key": model_key, "model_fo": model_fo},
            )
        await db.execute(
            text("""
                INSERT INTO migration_history (version) VALUES (:version)
                ON DUPLICATE KEY UPDATE version = VALUES(version)
            """),
            {"version": MIGRATION_VERSION},
        )
        await db.commit()
    result: dict[str, int | str] = {"version": MIGRATION_VERSION, "upserted": len(mappings)}
    logger.info("Synchronized %d model-to-FO mappings from the seed file", len(mappings))
    return result
