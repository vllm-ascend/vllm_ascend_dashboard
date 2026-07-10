"""
Agent 记忆系统数据模型

AnalysisMemory  — 统一记忆表，存储 CI 分析 / 每日总结 / Commit 分析的历史记录
AnalysisEmbedding — 向量表，存储记忆的 embedding（预留，阶段二使用）
"""
from datetime import UTC, datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.models import Base


class AnalysisMemory(Base):
    """
    统一分析记忆表

    存储所有 agent 分析任务的结果，供后续检索复用。
    三个业务场景通过 memory_type 区分：
      - failure_analysis  → CI 失败分析
      - daily_summary     → 每日总结
      - commit_analysis   → Commit 分析
    """
    __tablename__ = "analysis_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_type = Column(String(30), nullable=False, index=True,
                         comment="failure_analysis / daily_summary / commit_analysis")
    source_id = Column(Integer, index=True,
                       comment="关联的业务表 ID（如 JobFailureAnalysis.id）")
    title = Column(String(300), comment="一句话摘要")
    content = Column(Text, comment="报告全文")
    tags = Column(JSON, default=lambda: [], comment="自动提取的标签列表")
    metadata_ = Column("metadata", JSON, default=lambda: {},
                       comment="结构化元数据 {workflow_name, category, pr_number, ...}")
    summary = Column(String(500), comment="精简摘要，用于列表展示")
    status = Column(String(20), default="active", index=True,
                    comment="active / archived")
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC))


class AnalysisEmbedding(Base):
    """
    记忆向量表（阶段二启用）

    存储每条记忆的 embedding 向量，用于语义相似度检索。
    阶段一使用关键词标签匹配，本表预留。
    """
    __tablename__ = "analysis_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(Integer, ForeignKey("analysis_memories.id"),
                       nullable=False, index=True)
    embedding = Column(JSON, comment="向量数据 [0.12, -0.34, ...]")
    model = Column(String(50), comment="embedding 模型名称")
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))

    memory = relationship("AnalysisMemory", backref="embeddings", cascade="all")
