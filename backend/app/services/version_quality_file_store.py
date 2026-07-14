"""
版本质量评估报告文件存储

将生成的 HTML 报告及元数据存储到 data/version-quality-reports/ 目录。
每个报告保存为 {report_id}.json（包含元数据 + html 内容），另存一份 {report_id}.html 供直接下载。
"""
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def _sanitize_component(component: str) -> str:
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', component)
    if not sanitized:
        sanitized = 'unknown'
    if len(sanitized) > 50:
        suffix = hashlib.md5(component.encode()).hexdigest()[:8]
        sanitized = sanitized[:30] + '_' + suffix
    return sanitized


# report_id 只允许字母、数字、下划线、连字符、点（防止路径遍历）
_REPORT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_.-]+$')


class VersionQualityFileStore:
    """版本质量评估报告文件存储"""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = Path(settings.DATA_DIR) / "version-quality-reports"
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _report_id(self, base_tag: str, head_tag: str) -> str:
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"{_sanitize_component(base_tag)}_to_{_sanitize_component(head_tag)}_{ts}"

    @staticmethod
    def _validate_report_id(report_id: str) -> None:
        """校验 report_id 格式，防止路径遍历攻击"""
        if not report_id or not _REPORT_ID_PATTERN.match(report_id):
            raise ValueError("Invalid report_id format")

    def _safe_path(self, report_id: str, ext: str) -> Path:
        """安全地拼接文件路径，确保解析后在 base_dir 内"""
        self._validate_report_id(report_id)
        path = (self.base_dir / f"{report_id}.{ext}").resolve()
        if not path.is_relative_to(self.base_dir):
            raise ValueError("Invalid report_id: path escapes base directory")
        return path

    def _meta_path(self, report_id: str) -> Path:
        return self._safe_path(report_id, "json")

    def _html_path(self, report_id: str) -> Path:
        return self._safe_path(report_id, "html")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def save_report(
        self,
        base_tag: str,
        head_tag: str,
        html_content: str,
        metadata: dict,
    ) -> dict:
        """保存报告，返回包含 report_id 和元数据的字典"""
        report_id = self._report_id(base_tag, head_tag)

        full_meta = {
            "report_id": report_id,
            "base_tag": base_tag,
            "head_tag": head_tag,
            "generated_at": datetime.now(UTC).isoformat(),
            "html_length": len(html_content),
            **metadata,
        }

        # 保存元数据 JSON
        meta_path = self._meta_path(report_id)
        tmp = str(meta_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(full_meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, meta_path)

        # 保存 HTML 文件
        html_path = self._html_path(report_id)
        tmp_html = str(html_path) + ".tmp"
        with open(tmp_html, "w", encoding="utf-8") as f:
            f.write(html_content)
        os.replace(tmp_html, html_path)

        logger.info(
            "Saved version quality report: %s (%d chars HTML)",
            report_id, len(html_content),
        )
        return full_meta

    async def list_reports(self) -> list[dict]:
        """列出所有报告元数据，按生成时间倒序"""
        reports: list[dict] = []
        if not self.base_dir.exists():
            return reports

        for entry in self.base_dir.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                try:
                    with open(entry, encoding="utf-8") as f:
                        meta = json.load(f)
                    reports.append(meta)
                except Exception as e:
                    logger.warning("Failed to read report metadata %s: %s", entry, e)

        reports.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
        return reports

    async def find_report_by_tags(self, base_tag: str, head_tag: str) -> dict | None:
        """按 base/head tag 查找最新报告（避免遍历全部文件）"""
        if not self.base_dir.exists():
            return None
        prefix = f"{_sanitize_component(base_tag)}_to_{_sanitize_component(head_tag)}_"
        candidates: list[tuple[str, str]] = []
        for entry in self.base_dir.iterdir():
            if entry.is_file() and entry.name.startswith(prefix) and entry.suffix == ".json":
                candidates.append(entry.name)
        if not candidates:
            return None
        # 按文件名排序（时间戳在文件名中，最新在最后）
        candidates.sort(reverse=True)
        latest = candidates[0]
        try:
            latest_path = (self.base_dir / latest).resolve()
            if not latest_path.is_relative_to(self.base_dir):
                return None
            with open(latest_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to read matching report %s: %s", latest, e)
            return None

    async def get_report_meta(self, report_id: str) -> dict | None:
        """获取单个报告元数据"""
        try:
            meta_path = self._meta_path(report_id)
        except ValueError:
            return None
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to read report metadata %s: %s", report_id, e)
            return None

    async def get_report_html(self, report_id: str) -> str | None:
        """获取单个报告 HTML 内容"""
        try:
            html_path = self._html_path(report_id)
        except ValueError:
            return None
        if not html_path.exists():
            return None
        try:
            with open(html_path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("Failed to read report html %s: %s", report_id, e)
            return None

    async def get_html_path(self, report_id: str) -> Path | None:
        """获取 HTML 文件路径（用于 FileResponse 下载）"""
        try:
            html_path = self._html_path(report_id)
        except ValueError:
            return None
        if html_path.exists():
            return html_path
        return None

    async def delete_report(self, report_id: str) -> bool:
        """删除报告"""
        try:
            paths = (self._meta_path(report_id), self._html_path(report_id))
        except ValueError:
            return False
        deleted = False
        for path in paths:
            if path.exists():
                try:
                    path.unlink()
                    deleted = True
                except Exception as e:
                    logger.error("Failed to delete %s: %s", path, e)
        return deleted
