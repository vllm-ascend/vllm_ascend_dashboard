import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def sanitize_path_component(component: str) -> str:
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', component)
    if not sanitized:
        sanitized = 'unknown'
    return sanitized


class FailureAnalysisFileStore:

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = Path(settings.DATA_DIR) / "failure-analysis"
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_report_dir(self, workflow_name: str, job_name: str) -> Path:
        wf_dir = sanitize_path_component(workflow_name)
        job_dir = sanitize_path_component(job_name)
        report_dir = Path(os.path.join(str(self.base_dir), wf_dir, job_dir))
        os.makedirs(report_dir, exist_ok=True)
        return report_dir

    async def get_report_path(self, workflow_name: str, job_name: str, job_id: int) -> str:
        report_dir = self._get_report_dir(workflow_name, job_name)
        return os.path.join(str(report_dir), f"{job_id}.md")

    async def save_report(self, workflow_name: str, job_name: str, job_id: int, content: str) -> str:
        file_path = await self.get_report_path(workflow_name, job_name, job_id)
        temp_path = file_path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_path, file_path)
            logger.info(f"Saved failure analysis report for {workflow_name}/{job_name}/{job_id}")
            return file_path
        except Exception as e:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            logger.error(f"Failed to save failure analysis report: {e}")
            raise

    async def read_report(self, workflow_name: str, job_name: str, job_id: int) -> Optional[str]:
        file_path = await self.get_report_path(workflow_name, job_name, job_id)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Failed to read failure analysis report from {file_path}: {e}")
            return None

    async def delete_report(self, workflow_name: str, job_name: str, job_id: int) -> bool:
        file_path = await self.get_report_path(workflow_name, job_name, job_id)
        if os.path.exists(file_path):
            try:
                os.unlink(file_path)
                logger.info(f"Deleted failure analysis report for {workflow_name}/{job_name}/{job_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete failure analysis report: {e}")
        return False

    async def read_report_by_path(self, file_path: str) -> Optional[str]:
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Failed to read failure analysis report from {file_path}: {e}")
            return None
