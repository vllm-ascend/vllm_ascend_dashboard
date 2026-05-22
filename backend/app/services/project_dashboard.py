"""
Project Dashboard Service
Provides data for the vllm-ascend project dashboard
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.github_cache import get_github_cache, DOCKER_MIRRORS

logger = logging.getLogger(__name__)


class ProjectDashboardService:
    """项目看板服务"""

    def __init__(self):
        self.github_cache = get_github_cache()

    def get_releases(self, recommended_only: bool = False) -> List[Dict[str, Any]]:
        """获取 release 版本信息

        Args:
            recommended_only: 如果为 True，只返回推荐版本（最新 1 个 stable + 最新 1 个 pre-release）
        """
        return self.github_cache.get_releases(recommended_only=recommended_only)

    def get_all_tags(self) -> List[str]:
        """获取所有 tags 列表"""
        return self.github_cache.get_all_tags()

    def get_main_branch_versions(self) -> Optional[Dict[str, Any]]:
        """获取 main 分支的 vllm 版本信息"""
        versions = self.github_cache.get_conf_py_versions()
        if not versions:
            return None

        # Use available version fields from conf.py
        # main_vllm_tag/main_vllm_commit for main branch vLLM info
        # 空字符串 "" 表示无数据，直接返回（不回退到其他字段）
        vllm_version = versions.get("main_vllm_tag") or ""
        vllm_commit = versions.get("main_vllm_commit") or ""

        return {
            "vllm_version": vllm_version,
            "vllm_commit": vllm_commit,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def get_model_support_matrix(self) -> Optional[Dict[str, Any]]:
        """获取模型支持矩阵（从数据库配置）"""
        # 这个方法已废弃，模型支持矩阵现在完全由用户在后台配置
        # 不再从 GitHub markdown 文件解析
        return None

    def update_model_support_matrix(self, entries: List[Dict[str, Any]]) -> bool:
        """更新模型支持矩阵（保存到配置）"""
        # This will be saved to database via the config API
        return True

    def get_stale_issues(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取超期未 review 的 issues"""
        # This requires GitHub API access, will be implemented later
        # For now, return empty list
        logger.warning("get_stale_issues not yet implemented - requires GitHub API")
        return []


# Singleton instance
_service_instance: Optional[ProjectDashboardService] = None


def get_project_dashboard_service() -> ProjectDashboardService:
    """获取项目看板服务单例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = ProjectDashboardService()
    return _service_instance
