"""Create the normalized CI NPU job facts and durable sync-state tables."""
from __future__ import annotations

import logging

from sqlalchemy import text

from infrastructure.db.base import SessionLocal

logger = logging.getLogger("ci_npu_facts_migration")
MIGRATION_VERSION = "20261009_01_ci_npu_job_facts"


async def run() -> str:
    async with SessionLocal() as db:
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS ci_npu_job_facts (
              id BIGINT NOT NULL AUTO_INCREMENT,
              job_id BIGINT NOT NULL,
              run_id BIGINT NOT NULL,
              repository VARCHAR(255) NOT NULL,
              workflow_name VARCHAR(255) NULL,
              job_name VARCHAR(500) NULL,
              pr_number INT NULL,
              run_url VARCHAR(500) NULL,
              job_url VARCHAR(500) NULL,
              queued_at TIMESTAMP NULL,
              queued_at_source VARCHAR(64) NOT NULL,
              started_at TIMESTAMP NULL,
              completed_at TIMESTAMP NULL,
              status VARCHAR(32) NULL,
              conclusion VARCHAR(64) NULL,
              runner_labels JSON NULL,
              rule_version VARCHAR(64) NOT NULL,
              pool VARCHAR(128) NULL,
              accelerator_model VARCHAR(64) NULL,
              mapped_cards INT NULL,
              mapping_status VARCHAR(32) NOT NULL,
              data_quality_status VARCHAR(64) NOT NULL,
              source_updated_at TIMESTAMP NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uq_ci_npu_job_facts_job (job_id),
              KEY ix_ci_npu_facts_queued (queued_at),
              KEY ix_ci_npu_facts_started (started_at),
              KEY ix_ci_npu_facts_completed (completed_at),
              KEY ix_ci_npu_facts_repository (repository),
              KEY ix_ci_npu_facts_pool (pool),
              KEY ix_ci_npu_facts_run (run_id),
              KEY ix_ci_npu_facts_pr (pr_number),
              KEY ix_ci_npu_facts_repository_queued (repository, queued_at),
              KEY ix_ci_npu_facts_pool_status (pool, status)
            ) ENGINE=InnoDB
        """))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS ci_npu_sync_state (
              id BIGINT NOT NULL AUTO_INCREMENT,
              repository VARCHAR(255) NOT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'idle',
              successful_watermark TIMESTAMP NULL,
              last_successful_sync TIMESTAMP NULL,
              last_job_id BIGINT NULL,
              active_task_id VARCHAR(64) NULL,
              error_message TEXT NULL,
              rule_version VARCHAR(64) NULL,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uq_ci_npu_sync_state_repository (repository)
            ) ENGINE=InnoDB
        """))
        await db.execute(text("""
            INSERT INTO migration_history (version) VALUES (:version)
            ON DUPLICATE KEY UPDATE version = VALUES(version)
        """), {"version": MIGRATION_VERSION})
        await db.commit()
    logger.info("Applied CI NPU facts migration %s", MIGRATION_VERSION)
    return MIGRATION_VERSION
