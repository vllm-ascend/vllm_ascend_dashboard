from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

DIRECTORY_COLUMN = "目录"
CASE_NAME_COLUMN = "用例名字"
CARD_COUNT_COLUMN = "几卡"
REMARK_COLUMN = "备注"
UNMATCHED_REMARK = "未直接命中特性池"


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_case_matrix_path() -> Path:
    configured = Path(settings.TEST_BOARD_CASE_MATRIX_PATH)
    if configured.is_absolute():
        return configured
    return (_backend_root() / configured).resolve()


def _build_feature_key(title: str, index: int, used_keys: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    if not base:
        base = f"feature_{index}"

    candidate = base
    suffix = 2
    while candidate in used_keys:
        candidate = f"{base}_{suffix}"
        suffix += 1

    used_keys.add(candidate)
    return candidate


@lru_cache(maxsize=4)
def _load_case_feature_matrix_cached(path_str: str, mtime: float) -> dict[str, Any]:
    del mtime
    path = Path(path_str)

    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        fieldnames = reader.fieldnames or []
        raw_rows = list(reader)

    feature_titles = [
        name for name in fieldnames
        if name not in {DIRECTORY_COLUMN, CASE_NAME_COLUMN, CARD_COUNT_COLUMN, REMARK_COLUMN}
    ]

    used_keys: set[str] = set()
    feature_key_map = {
        title: _build_feature_key(title, index, used_keys)
        for index, title in enumerate(feature_titles, start=1)
    }
    feature_counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    directory_counts: Counter[str] = Counter()
    card_count_counts: Counter[str] = Counter()
    remark_counts: Counter[str] = Counter()

    for index, raw_row in enumerate(raw_rows, start=1):
        directory = (raw_row.get(DIRECTORY_COLUMN) or "").strip()
        case_name = (raw_row.get(CASE_NAME_COLUMN) or "").strip()
        card_count = (raw_row.get(CARD_COUNT_COLUMN) or "").strip() or None
        remark = (raw_row.get(REMARK_COLUMN) or "").strip() or None

        if not case_name:
            logger.debug("Skipping empty case name row %s in %s", index, path)
            continue

        features: dict[str, str] = {}
        for title in feature_titles:
            cell_value = (raw_row.get(title) or "").strip()
            if not cell_value:
                continue
            feature_key = feature_key_map[title]
            features[feature_key] = cell_value
            feature_counts[feature_key] += 1

        rows.append({
            "id": f"case-matrix-{index}",
            "directory": directory,
            "case_name": case_name,
            "card_count": card_count,
            "remark": remark,
            "marked_feature_count": len(features),
            "features": features,
        })

        if directory:
            directory_counts[directory] += 1
        if card_count:
            card_count_counts[card_count] += 1
        if remark:
            remark_counts[remark] += 1

    feature_columns = [
        {
            "key": feature_key_map[title],
            "title": title,
            "count": feature_counts.get(feature_key_map[title], 0),
        }
        for title in feature_titles
    ]

    updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

    return {
        "source_file": path.name,
        "updated_at": updated_at,
        "feature_columns": feature_columns,
        "rows": rows,
        "statistics": {
            "total_cases": len(rows),
            "total_features": len(feature_columns),
            "unmatched_cases": remark_counts.get(UNMATCHED_REMARK, 0),
            "by_directory": dict(directory_counts),
            "by_card_count": dict(card_count_counts),
            "by_remark": dict(remark_counts),
        },
    }


def get_case_feature_matrix() -> dict[str, Any]:
    path = resolve_case_matrix_path()
    if not path.is_file():
        raise FileNotFoundError(f"Case matrix file not found: {path}")
    return _load_case_feature_matrix_cached(str(path), path.stat().st_mtime)
