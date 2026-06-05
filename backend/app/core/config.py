"""
核心配置模块
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # 应用配置
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # GitHub 配置
    GITHUB_TOKEN: str
    GITHUB_OWNER: str = "vllm-project"
    GITHUB_REPO: str = "vllm-ascend"

    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"

    # JWT 配置
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    KUBECONFIG_ENCRYPTION_KEY: str | None = None

    # CORS 配置
    # 生产环境应明确指定允许的域名，不要使用 "*"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # 数据目录
    DATA_DIR: str = "data"  # 数据文件存储目录

    # 数据同步配置
    CI_SYNC_INTERVAL_MINUTES: int = 720  # CI 数据同步间隔（分钟），默认 12 小时
    CI_SYNC_DAYS_BACK: int = 7  # 自动同步时采集最近 N 天的数据
    CI_SYNC_MAX_RUNS_PER_WORKFLOW: int = 100  # 每个 workflow 最多采集多少条记录
    CI_SYNC_FORCE_FULL_REFRESH: bool = False  # 是否强制全量覆盖刷新
    DATA_RETENTION_DAYS: int = 365

    # 模型同步配置
    MODEL_SYNC_INTERVAL_MINUTES: int = 60  # 模型报告同步间隔（分钟），默认 1 小时
    MODEL_SYNC_RUNS_LIMIT: int = 100  # 每个 workflow 最多获取最近 N 次 runs
    MODEL_SYNC_DAYS_BACK: int = 3  # 自动同步时采集最近 N 天的数据

    # Project Dashboard 配置
    PROJECT_DASHBOARD_CACHE_INTERVAL_MINUTES: int = 60  # Project Dashboard Git 仓库缓存更新间隔（分钟），默认 60 分钟
    GITHUB_CACHE_DIR: str = ""  # GitHub 本地缓存目录，默认为根目录 data/repos/

    # 每日总结配置
    DAILY_SUMMARY_ENABLED: bool = True  # 是否启用每日总结生成任务
    DAILY_SUMMARY_CRON_HOUR: int = 8  # 每日总结生成时间（小时），默认早上 8 点
    DAILY_SUMMARY_CRON_MINUTE: int = 0  # 每日总结生成时间（分钟）

    # 每日运行报告邮件推送配置
    REPORT_ENABLED: bool = True
    REPORT_SCHEDULE_HOUR: int = 8
    REPORT_SCHEDULE_MINUTE: int = 30
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    REPORT_FROM_EMAIL: str = ""
    REPORT_RECIPIENTS: str = ""
    REPORT_CC_RECIPIENTS: str = ""
    REPORT_SUBJECT_TEMPLATE: str = "vLLM Ascend 运行报告 - {date}"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """验证 JWT 密钥长度"""
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return v

    @field_validator("GITHUB_TOKEN")
    @classmethod
    def validate_github_token(cls, v: str) -> str:
        """验证 GitHub Token 格式"""
        if not (v.startswith("ghp_") or v.startswith("github_pat_") or len(v) >= 10):
            raise ValueError("GITHUB_TOKEN must be a valid GitHub token (ghp_*, github_pat_*, or valid length)")
        return v

    @field_validator("REPORT_RECIPIENTS")
    @classmethod
    def validate_recipients(cls, v: str) -> str:
        """验证报告收件人格式"""
        if v and not all("@" in r.strip() for r in v.split(",")):
            raise ValueError("REPORT_RECIPIENTS must be valid email addresses separated by commas")
        return v

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.ENVIRONMENT == "production"


# 全局配置实例
settings = Settings()
