from pydantic import BaseModel, Field, model_validator, field_validator
from typing import Literal, Optional


class IssueDiagnosisMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=100000)


class IssueDiagnosisRequest(BaseModel):
    data_source_type: str = Field(
        ...,
        description="数据源类型: pr_pipeline, ci_job, commit, manual",
    )
    pr_number: Optional[int] = Field(
        None,
        description="PR 编号 (data_source_type=pr_pipeline 时必填)",
        gt=0,
    )
    job_id: Optional[int] = Field(
        None,
        description="CI Job ID (data_source_type=ci_job时推荐提供)",
    )
    run_id: Optional[int] = Field(
        None,
        description="CI Run ID (用于commit数据源)",
    )
    commit_sha: Optional[str] = Field(
        None,
        description="Commit SHA (7-40位十六进制)",
        max_length=40,
    )
    user_prompt: Optional[str] = Field(
        None,
        description="用户补充提示词",
        max_length=20000,
    )
    conversation_history: list[IssueDiagnosisMessage] = Field(
        default_factory=list,
        description="当前页面会话中的历史问答",
        max_length=20,
    )

    @field_validator('commit_sha')
    @classmethod
    def validate_commit_sha(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            if not re.match(r'^[0-9a-f]{7,40}$', v):
                raise ValueError('commit_sha must be 7-40 hex characters')
        return v

    @model_validator(mode='after')
    def validate_data_source(self) -> 'IssueDiagnosisRequest':
        valid_types = ('pr_pipeline', 'ci_job', 'commit', 'manual')
        if self.data_source_type not in valid_types:
            raise ValueError(f'data_source_type must be one of {valid_types}')
        if self.data_source_type == 'pr_pipeline' and self.pr_number is None:
            raise ValueError('pr_number is required for pr_pipeline diagnosis')
        return self


class CIJobOption(BaseModel):
    job_id: int
    run_id: int
    workflow_name: str
    job_name: str
    conclusion: str
    completed_at: Optional[str] = None


class CommitOption(BaseModel):
    sha: str
    message: str
    committed_at: Optional[str] = None
    run_id: Optional[int] = None
    run_number: Optional[int] = None
