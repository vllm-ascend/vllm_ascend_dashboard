"""
每日总结数据模型

注意：
    DailyPR, DailyIssue, DailyCommit, DailySummary 表已迁移到文件存储。
    这些模型已弃用，将在未来版本中移除。
    新的每日数据存储在 data/daily-data/{project}/ 目录下。
"""
from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, Text, Date, Boolean, TIMESTAMP, UniqueConstraint
from sqlalchemy.types import JSON

# 从 __init__.py 导入 Base，确保所有模型使用同一个 Base
from . import Base


# ============ 已弃用的模型（数据已迁移到文件存储） ============

class DailyPR(Base):
    """
    每日 PR 数据表（已弃用）
    
    此表已迁移到文件存储：data/daily-data/{project}/{date}.json
    该模型保留仅用于向后兼容，将在未来版本中移除。
    """
    __tablename__ = "daily_prs"
    __table_args__ = {'extend_existing': True}  # 允许重新定义

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(String(100), nullable=False)
    pr_number = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    state = Column(String(20), nullable=False)
    author = Column(String(100), nullable=False)
    created_at = Column(TIMESTAMP)
    merged_at = Column(TIMESTAMP)
    html_url = Column(String(500), nullable=False)
    labels = Column(JSON)
    body = Column(Text)
    commits = Column(JSON, nullable=False)
    data_date = Column(Date, nullable=False)
    fetched_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class DailyIssue(Base):
    """
    每日 Issue 数据表（已弃用）
    
    此表已迁移到文件存储：data/daily-data/{project}/{date}.json
    该模型保留仅用于向后兼容，将在未来版本中移除。
    """
    __tablename__ = "daily_issues"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(String(100), nullable=False)
    issue_number = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    state = Column(String(20), nullable=False)
    author = Column(String(100), nullable=False)
    created_at = Column(TIMESTAMP)
    closed_at = Column(TIMESTAMP)
    html_url = Column(String(500), nullable=False)
    labels = Column(JSON)
    body = Column(Text)
    comments_count = Column(Integer, default=0)
    data_date = Column(Date, nullable=False)
    fetched_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class DailyCommit(Base):
    """
    每日 Commit 数据表（已弃用）
    
    此表已迁移到文件存储：data/daily-data/{project}/{date}.json
    该模型保留仅用于向后兼容，将在未来版本中移除。
    """
    __tablename__ = "daily_commits"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(String(100), nullable=False)
    sha = Column(String(40), nullable=False)
    short_sha = Column(String(7), nullable=False)
    message = Column(String(1000), nullable=False)
    full_message = Column(Text)
    author = Column(String(100), nullable=False)
    author_email = Column(String(200))
    committed_at = Column(TIMESTAMP)
    html_url = Column(String(500), nullable=False)
    pr_number = Column(Integer)
    pr_title = Column(String(500))
    pr_description = Column(Text)
    files_changed = Column(JSON)
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    data_date = Column(Date, nullable=False)
    fetched_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class DailySummary(Base):
    """
    每日 AI 总结表（已弃用）
    
    此表已迁移到文件存储：data/daily-data/{project}/summaries/{date}.md
    该模型保留仅用于向后兼容，将在未来版本中移除。
    """
    __tablename__ = "daily_summaries"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    project = Column(String(100), nullable=False)
    data_date = Column(Date, nullable=False)
    summary_markdown = Column(Text, nullable=False)
    has_data = Column(Boolean, default=True)
    pr_count = Column(Integer, default=0)
    issue_count = Column(Integer, default=0)
    commit_count = Column(Integer, default=0)
    llm_provider = Column(String(50))
    llm_model = Column(String(100))
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    generation_time_seconds = Column(Integer)
    status = Column(String(20), default='success')
    error_message = Column(Text)
    generated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    regenerated_at = Column(TIMESTAMP)


# ============ 仍然使用的模型 ============

class LLMProviderConfig(Base):
    """LLM 提供商配置表"""
    __tablename__ = "llm_provider_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    api_key = Column(String(500))  # API Key，直接存储（加密存储建议后续实现）
    api_base_url = Column(String(500))
    default_model = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True)
    is_active = Column(Boolean, default=False)  # 是否为当前激活的提供商（用于 AI 总结）
    display_order = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
