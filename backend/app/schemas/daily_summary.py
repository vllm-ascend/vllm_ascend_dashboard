"""
每日总结相关的 Pydantic Schemas
"""
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class GenerateSummaryRequest(BaseModel):
    """生成总结请求"""
    project: str = Field(..., description="项目标识 (ascend/vllm)")
    date: Optional[str] = Field(None, description="日期 (ISO format: YYYY-MM-DD), 默认为昨天")
    llm_provider: Optional[str] = Field(None, description="LLM 提供商 (openai/anthropic/qwen)")
    force_regenerate: bool = Field(False, description="是否强制重新生成")


class FetchDataRequest(BaseModel):
    """获取数据请求"""
    project: str = Field(..., description="项目标识 (ascend/vllm)")
    date: str = Field(..., description="日期 (ISO format: YYYY-MM-DD)")
    force_refresh: bool = Field(False, description="是否强制刷新（删除已有数据后重新采集）")


class DailySummaryResponse(BaseModel):
    """每日总结响应"""
    project: str
    date: str
    summary_markdown: str
    has_data: bool
    pr_count: int
    issue_count: int
    commit_count: int
    generated_at: Optional[str]
    status: Optional[str] = None


class DailySummaryListItem(BaseModel):
    """每日总结列表项"""
    date: str
    project: str
    pr_count: int
    issue_count: int
    commit_count: int
    has_data: bool
    generated_at: str


class DailySummaryListResponse(BaseModel):
    """每日总结列表响应"""
    total: int
    data: list[DailySummaryListItem]


class FetchDataResponse(BaseModel):
    """获取数据响应"""
    success: bool
    message: str
    data: dict


class GenerateSummaryResponse(BaseModel):
    """生成总结响应"""
    success: bool
    message: str
    data: dict


class LLMProviderResponse(BaseModel):
    """LLM 提供商响应"""
    provider: str
    display_name: str
    api_key_configured: bool
    default_model: str
    enabled: bool
    display_order: int


class DailySummaryConfigResponse(BaseModel):
    """每日总结配置响应"""
    enabled: bool
    cron_hour: int
    cron_minute: int
    timezone: str
    default_llm_provider: Optional[str]
    projects: list[dict]


class TrendDataItem(BaseModel):
    """趋势数据项"""
    date: str
    pr_count: int
    issue_count: int
    commit_count: int


class TrendDataResponse(BaseModel):
    """趋势数据响应"""
    project: str
    days: int
    data: list[TrendDataItem]
