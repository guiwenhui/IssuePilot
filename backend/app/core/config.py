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
    max_python_files: int = 2_000
    max_python_file_bytes: int = 1_048_576
    max_python_total_bytes: int = 20_971_520
    max_code_entities: int = 50_000
    parser_timeout_seconds: int = 30
    max_code_preview_entries: int = 2_000
    embedding_provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dimensions: int = 1_024
    embedding_timeout_seconds: int = 60
    embedding_batch_size: int = 32
    max_code_chunks: int = 10_000
    max_chunk_lines: int = 120
    max_symbol_chunk_lines: int = 160
    chunk_overlap_lines: int = 20
    max_chunk_characters: int = 16_384
    retrieval_candidate_limit: int = 50
    retrieval_result_limit: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
