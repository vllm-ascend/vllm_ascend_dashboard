"""
上游支持矩阵 Markdown 解析器

解析 vllm-ascend 仓库 docs/source/user_guide/support_matrix/ 目录下的 3 个 Markdown 文件：
- supported_models.md   → 模型注册数据 + 逐模型特性
- supported_features.md → 全局功能支持状态
- feature_matrix.md     → 25×25 特性互操作矩阵
"""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

DOC_BASE_URL = "https://docs.vllm.ai/projects/ascend/en/latest"

COLUMN_FEATURE_MAP = {
    "chunked prefill": "chunked_prefill",
    "automatic prefix cache": "automatic_prefix_cache",
    "lora": "lora",
    "speculative decoding": "speculative_decoding",
    "async scheduling": "async_scheduling",
    "tensor parallel": "tensor_parallel",
    "pipeline parallel": "pipeline_parallel",
    "expert parallel": "expert_parallel",
    "data parallel": "data_parallel",
    "prefill-decode disaggregation": "prefilled_decode_disaggregation",
    "piecewise aclgraph": "piecewise_aclgraph",
    "fullgraph aclgraph": "fullgraph_aclgraph",
    "mlp weight prefetch": "mlp_weight_prefetch",
}

EMOJI_STATUS_MAP = {
    "✅": "supported",
    "🔵": "experimental",
    "❌": "not_supported",
    "🟡": "untested",
}

COMPAT_EMOJI_MAP = {
    "✅": "full",
    "🟠": "partial",
    "❌": "none",
    "❔": "unknown",
}


def _strip_html(text: str) -> str:
    """去除 HTML 标签（<abbr>、<a> 等），保留纯文本"""
    return re.sub(r"<[^>]+>", "", text)


def _split_table_cells(line: str) -> list[str]:
    """拆分 Markdown 表格行，保留空单元格以维持列对齐"""
    raw = line.split("|")
    if raw and raw[0].strip() == "":
        raw = raw[1:]
    if raw and raw[-1].strip() == "":
        raw = raw[:-1]
    return [c.strip() for c in raw]


def _parse_support_status(text: str) -> str:
    """解析支持状态，区分空（unmarked）与 🟡（untested）"""
    text = text.strip()
    if not text:
        return "unmarked"
    for emoji, status in EMOJI_STATUS_MAP.items():
        if emoji in text:
            return status
    if "need test" in text.lower():
        return "untested"
    return "unmarked"


def _extract_link(text: str) -> str | None:
    """从 Markdown 链接 [text](url) 中提取 URL"""
    match = re.search(r"\[.*?\]\((.*?)\)", text)
    return match.group(1) if match else None


def _extract_issue_number(text: str) -> str | None:
    """从文本中提取 Issue 编号"""
    match = re.search(r"#(\d+)", text)
    return f"#{match.group(1)}" if match else None


def _build_absolute_url(relative_path: str | None) -> str | None:
    """将上游相对路径拼接为绝对 URL"""
    if not relative_path:
        return None
    if relative_path.startswith("http"):
        return relative_path
    clean = relative_path.lstrip("./")
    if clean.endswith(".md"):
        clean = clean[:-3] + ".html"
    return f"{DOC_BASE_URL}/{clean}"


def parse_supported_models(md_content: str) -> list[dict[str, Any]]:
    """解析 supported_models.md，返回模型注册数据 + 逐模型特性

    返回列表中每个元素是一个 dict，包含 ModelRegistry 字段 + features dict。
    features dict 的 key 是 feature_key，value 是 feature_status。
    """
    results: list[dict[str, Any]] = []
    current_model_type = "text_generative"
    current_tier: str | None = None
    seen: set[tuple[str, str]] = set()
    columns: list[str] | None = None

    for line in md_content.splitlines():
        stripped = line.strip()

        if stripped.startswith("## "):
            title = stripped[3:].lower()
            if "text-only" in title:
                current_model_type = "text_generative"
            elif "multimodal" in title:
                current_model_type = "multimodal_generative"
            columns = None
        elif stripped.startswith("### "):
            title = stripped[4:].lower()
            if "pooling" in title:
                current_model_type = "pooling"
            columns = None
        elif stripped.startswith("#### "):
            title = stripped[5:].lower()
            current_tier = "core" if "core" in title else "extended"
            columns = None
        elif stripped.startswith("|") and current_tier:
            if re.match(r"^\|[\s\-:]+\|", stripped):
                continue
            cells = _split_table_cells(stripped)
            if columns is None:
                columns = [_strip_html(c).lower() for c in cells]
                continue
            if len(cells) < 2 or columns is None:
                continue
            row = dict(zip(columns, cells))
            model_name_raw = row.get("model", "").strip()
            model_name = _strip_html(model_name_raw)
            if not model_name:
                continue

            role = "pooling" if current_model_type == "pooling" else "generative"
            key = (model_name, role)
            if key in seen:
                continue
            seen.add(key)

            support_status = _parse_support_status(row.get("support", ""))
            weight_formats: list[str] = []
            if row.get("bf16", "").strip() == "✅":
                weight_formats.append("BF16")
            if row.get("w8a8", "").strip() == "✅":
                weight_formats.append("W8A8")

            hardware_raw = row.get("supported hardware", "").strip()
            supported_hardware = (
                [h.strip() for h in hardware_raw.split("/") if h.strip()]
                if hardware_raw
                else None
            )

            features: dict[str, str] = {}
            for col_name, feature_key in COLUMN_FEATURE_MAP.items():
                cell_value = row.get(col_name, "").strip()
                if cell_value:
                    features[feature_key] = _parse_support_status(cell_value)

            doc_raw = row.get("doc", "").strip()
            doc_url = _build_absolute_url(_extract_link(doc_raw)) if doc_raw else None

            note_raw = row.get("note", "").strip()
            upstream_issue = _extract_issue_number(note_raw)

            results.append({
                "display_name": model_name,
                "model_name": model_name,
                "role": role,
                "model_type": current_model_type,
                "tier": current_tier,
                "support_status": support_status,
                "weight_formats": weight_formats or None,
                "supported_hardware": supported_hardware,
                "max_model_len": row.get("max-model-len", "").strip() or None,
                "note": note_raw or None,
                "upstream_issue": upstream_issue,
                "official_doc_url": doc_url,
                "features": features,
            })
        else:
            if not stripped.startswith("|"):
                columns = None

    return results


def parse_supported_features(md_content: str) -> list[dict[str, Any]]:
    """解析 supported_features.md，返回全局功能支持状态列表"""
    results: list[dict[str, Any]] = []
    columns: list[str] | None = None

    for line in md_content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:]+\|", stripped):
            continue
        cells = _split_table_cells(stripped)
        if columns is None:
            columns = [c.strip().lower() for c in cells]
            continue
        row = dict(zip(columns, cells))
        results.append({
            "feature": row.get("feature", "").strip(),
            "status": row.get("status", "").strip(),
            "next_step": row.get("next step", "").strip(),
        })

    return results


def parse_feature_compatibility(md_content: str) -> list[dict[str, Any]]:
    """解析 feature_matrix.md，返回 25×25 特性互操作矩阵

    返回列表中每个元素是 {feature_a, feature_b, compatibility, footnote}。
    仅返回下三角非空单元格（含对角线跳过）。
    """
    footnotes: dict[str, str] = {}
    footnote_pattern = re.compile(r"-\s*<sup>(\d+)</sup>\s*(.+)")
    for line in md_content.splitlines():
        m = footnote_pattern.match(line.strip())
        if m:
            footnotes[m.group(1)] = m.group(2).strip()

    results: list[dict[str, Any]] = []
    columns: list[str] | None = None

    for line in md_content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:]+\|", stripped):
            continue

        cells = _split_table_cells(stripped)
        cells_clean = [_strip_html(c) for c in cells]

        if columns is None:
            columns = cells_clean[1:]
            continue

        if len(cells_clean) < 2:
            continue

        row_feature = cells_clean[0]
        for i, cell in enumerate(cells_clean[1:]):
            if i >= len(columns):
                break
            col_feature = columns[i]
            if row_feature == col_feature:
                continue
            cell_stripped = cell.strip()
            if not cell_stripped:
                continue

            compatibility = "unknown"
            for emoji, status in COMPAT_EMOJI_MAP.items():
                if emoji in cell_stripped:
                    compatibility = status
                    break

            footnote = None
            sup_match = re.search(r"<sup>(\d+)</sup>", cell)
            if sup_match:
                footnote = footnotes.get(sup_match.group(1))

            results.append({
                "feature_a": row_feature,
                "feature_b": col_feature,
                "compatibility": compatibility,
                "footnote": footnote,
            })

    return results
