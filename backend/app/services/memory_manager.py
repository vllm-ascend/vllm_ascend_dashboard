"""
Agent 记忆管理器

提供分析记忆的存储（memorize）、检索（recall）、归档（forget）能力。

阶段一检索策略：关键词 + 标签匹配（SQL 查询）
阶段二（后续）：加入向量语义检索（embedding 相似度）
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import AnalysisMemory, AnalysisEmbedding

logger = logging.getLogger(__name__)

# 中文/英文关键词提取：匹配连续的中文字符或英文单词
_KEYWORD_RE = re.compile(r"[一-鿿]{2,}|[a-zA-Z_]{3,}")

# 停用词（排除太宽泛的关键词）
_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "not",
    "are", "was", "were", "can", "all", "has", "had", "but", "did", "get",
    "error", "failed", "fail", "failure", "job", "test", "tests",
    "日志", "错误", "失败", "分析", "问题", "检查", "可能",
}


@dataclass
class MemoryRecord:
    """一条记忆记录"""
    memory_type: str
    source_id: int | None = None
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    summary: str = ""


@dataclass
class MemorySearchResult:
    """记忆检索结果"""
    id: int
    memory_type: str
    title: str
    content: str
    tags: list[str]
    metadata: dict
    summary: str
    score: float  # 相关性分数（0~1）


def extract_keywords(text: str, max_keywords: int = 10) -> list[str]:
    """从文本中提取关键词"""
    words = _KEYWORD_RE.findall(text)
    seen = set()
    result = []
    for w in words:
        wl = w.lower()
        if wl not in _STOP_WORDS and wl not in seen:
            seen.add(wl)
            result.append(w)
            if len(result) >= max_keywords:
                break
    return result


class MemoryManager:
    """分析记忆管理器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recall_sync(
        self,
        query: str,
        memory_type: str,
        filters: dict | None = None,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """
        recall() 的同步包装，供 smolagents 同步工具在非主线程中调用。

        安全处理 event loop 生命周期：
          - 如果当前线程有运行中的 event loop → 在该 loop 上 schedule
          - 否则 → 用 asyncio.run() 创建临时 loop
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的 loop（agent 线程），直接用 asyncio.run()
            return asyncio.run(self.recall(query, memory_type, filters, limit))

        # 有运行中的 loop（少见的同步调用场景），抛错提示用异步版本
        raise RuntimeError(
            "Cannot call recall_sync() from within a running event loop. "
            "Use await recall() instead."
        )

    async def recall(
        self,
        query: str,
        memory_type: str,
        filters: dict | None = None,
        limit: int = 5,
    ) -> list[MemorySearchResult]:
        """
        检索相关历史记忆。

        Args:
            query: 当前分析查询文本
            memory_type: 记忆类型
            filters: 可选的元数据过滤条件，如 {"workflow_name": "nightly-A2"}
            limit: 返回最多 N 条

        Returns:
            按相关性排序的记忆列表
        """
        keywords = extract_keywords(query)
        if not keywords:
            # 没有关键词时，按时间返回最近的同类记忆
            return await self._recall_recent(memory_type, filters, limit)

        # 构建标签匹配查询
        results = await self._recall_by_tags(keywords, memory_type, filters, limit)
        return results

    async def memorize(self, record: MemoryRecord) -> int:
        """
        存储一条记忆。

        Returns:
            新记忆的 ID
        """
        tags = record.tags or extract_keywords(record.content)
        summary = record.summary or (
            record.content[:300] if record.content else ""
        )

        memory = AnalysisMemory(
            memory_type=record.memory_type,
            source_id=record.source_id,
            title=record.title or "",
            content=record.content or "",
            tags=tags,
            metadata=record.metadata or {},
            summary=summary,
            status="active",
        )
        self.db.add(memory)
        await self.db.flush()
        await self.db.refresh(memory)

        logger.info(
            "Memory stored: id=%d type=%s title=%s tags=%s",
            memory.id, memory.memory_type, memory.title[:80], tags[:5],
        )
        return memory.id

    async def forget(self, memory_id: int) -> bool:
        """
        归档一条记忆（软删除）。

        Returns:
            True 表示成功归档，False 表示未找到
        """
        stmt = select(AnalysisMemory).where(
            AnalysisMemory.id == memory_id,
            AnalysisMemory.status == "active",
        )
        result = await self.db.execute(stmt)
        memory = result.scalar_one_or_none()
        if not memory:
            return False

        memory.status = "archived"
        memory.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        logger.info("Memory archived: id=%d", memory_id)
        return True

    async def list_memories(
        self,
        memory_type: str,
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemorySearchResult]:
        """分页列出记忆"""
        stmt = (
            select(AnalysisMemory)
            .where(
                AnalysisMemory.memory_type == memory_type,
                AnalysisMemory.status == status,
            )
            .order_by(AnalysisMemory.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [
            self._to_search_result(row, score=0.0)
            for row in result.scalars().all()
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _recall_by_tags(
        self,
        keywords: list[str],
        memory_type: str,
        filters: dict | None,
        limit: int,
    ) -> list[MemorySearchResult]:
        """通过标签匹配检索记忆（metadata 过滤在 Python 层，兼容 SQLite）"""
        conditions = [
            AnalysisMemory.memory_type == memory_type,
            AnalysisMemory.status == "active",
        ]

        # 取最近记录（不在此层做 metadata 过滤，避免 SQLite JSON path 兼容问题）
        stmt = (
            select(AnalysisMemory)
            .where(and_(*conditions))
            .order_by(AnalysisMemory.created_at.desc())
            .limit(limit * 3)
        )
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        if not memories:
            return []

        # Python 层过滤：metadata 精确匹配
        if filters:
            memories = [
                m for m in memories
                if all(
                    str(m.metadata_.get(k, "")) == str(v)
                    for k, v in filters.items()
                )
            ]

        # 按标签命中数排序
        keyword_lower = {k.lower() for k in keywords}
        scored = []
        for m in memories:
            tags_lower = {t.lower() for t in (m.tags or [])}
            hits = len(keyword_lower & tags_lower)
            if hits > 0:
                scored.append((hits / max(len(keyword_lower), 1), m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            self._to_search_result(m, score=round(s, 3))
            for s, m in scored[:limit]
        ]

    async def _recall_recent(
        self,
        memory_type: str,
        filters: dict | None,
        limit: int,
    ) -> list[MemorySearchResult]:
        """按时间返回最近的记忆（metadata 过滤在 Python 层，兼容 SQLite）"""
        conditions = [
            AnalysisMemory.memory_type == memory_type,
            AnalysisMemory.status == "active",
        ]

        stmt = (
            select(AnalysisMemory)
            .where(and_(*conditions))
            .order_by(AnalysisMemory.created_at.desc())
            .limit(limit * 2 if filters else limit)
        )
        result = await self.db.execute(stmt)
        memories = result.scalars().all()

        # Python 层过滤：metadata 精确匹配
        if filters:
            memories = [
                m for m in memories
                if all(
                    str(m.metadata_.get(k, "")) == str(v)
                    for k, v in filters.items()
                )
            ][:limit]

        return [
            self._to_search_result(m, score=0.0)
            for m in memories
        ]
        ]

    @staticmethod
    def _to_search_result(memory: AnalysisMemory, score: float) -> MemorySearchResult:
        return MemorySearchResult(
            id=memory.id,
            memory_type=memory.memory_type,
            title=memory.title or "",
            content=memory.content or "",
            tags=memory.tags or [],
            metadata=memory.metadata_ or {},
            summary=memory.summary or "",
            score=score,
        )

    @staticmethod
    def format_memories_for_prompt(memories: list[MemorySearchResult]) -> str:
        """将记忆列表格式化为可注入 system prompt 的文本"""
        if not memories:
            return ""

        lines = ["\n## 历史分析记录（参考）\n"]
        for i, m in enumerate(memories, 1):
            lines.append(f"### 记录 {i}：{m.title}")
            if m.tags:
                lines.append(f"标签：{', '.join(m.tags[:10])}")
            lines.append(f"```\n{m.summary}\n```")
            lines.append("")
        return "\n".join(lines)
