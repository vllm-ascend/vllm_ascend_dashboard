from pydantic import BaseModel, Field, model_validator
from typing import Optional


class IssueDiagnosisRequest(BaseModel):
    data_source_type: str = Field(
        ...,
        description="数据源类型: ci_job, commit, manual",
    )
    job_id: Optional[int] = Field(
        None,
        description="CI Job ID (data_source_type=ci_job时必填)",
    )
    run_id: Optional[int] = Field(
        None,
        description="CI Run ID (用于commit数据源)",
    )
    commit_sha: Optional[str] = Field(
        None,
        description="Commit SHA (data_source_type=commit时可选)",
    )
    user_prompt: Optional[str] = Field(
        None,
        description="用户补充提示词",
    )

    @model_validator(mode='after')
    def validate_data_source(self) -> 'IssueDiagnosisRequest':
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
