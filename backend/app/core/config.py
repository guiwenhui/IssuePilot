from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IssuePilot API"
    database_url: str = (
        "postgresql+asyncpg://issuepilot:issuepilot@localhost:54329/issuepilot"
    )
    frontend_origin: str = "http://localhost:3000"
    repository_clone_enabled: bool = True
    repository_workspace_root: str = "/tmp/issuepilot-workspaces"
    clone_timeout_seconds: int = 60
    max_workspace_bytes: int = 104_857_600
    max_tracked_files: int = 5_000
    max_tree_entries: int = 2_000
    max_tree_depth: int = 25
    clone_queue_capacity: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
