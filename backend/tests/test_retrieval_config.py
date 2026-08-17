from app.core.config import Settings
from app.schemas.task import TaskStatus


def test_m4_embedding_defaults_are_local_and_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_provider == "ollama"
    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.embedding_model == "qwen3-embedding:0.6b"
    assert settings.embedding_dimensions == 1024
    assert settings.embedding_batch_size == 32
    assert settings.embedding_timeout_seconds == 60
    assert settings.max_code_chunks == 10_000
    assert settings.max_chunk_lines == 120
    assert settings.max_symbol_chunk_lines == 160
    assert settings.chunk_overlap_lines == 20
    assert settings.max_chunk_characters == 16_384
    assert settings.retrieval_candidate_limit == 50
    assert settings.retrieval_result_limit == 10


def test_m4_task_states_are_explicit() -> None:
    assert TaskStatus.RETRIEVING.value == "retrieving"
    assert TaskStatus.RETRIEVED.value == "retrieved"
