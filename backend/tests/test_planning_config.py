import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_repository_runtime
from app.schemas.task import TaskStatus


def test_m5_planning_defaults_are_local_and_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.planning_enabled is True
    assert settings.llm_provider == "ollama"
    assert settings.llm_model == "qwen3:8b"
    assert settings.llm_base_url == "http://127.0.0.1:11434"
    assert settings.llm_timeout_seconds == 180
    assert settings.llm_context_window == 16_384
    assert settings.llm_max_output_tokens == 2_048
    assert settings.llm_max_response_bytes == 65_536
    assert settings.planning_evidence_limit == 10
    assert settings.planning_max_snippet_characters == 3_000
    assert settings.planning_max_evidence_characters == 20_000


def test_m5_limits_reject_zero_or_excessive_evidence_count() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, planning_evidence_limit=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, planning_evidence_limit=11)


def test_m5_task_states_are_explicit() -> None:
    assert TaskStatus.ANALYZING.value == "analyzing"
    assert TaskStatus.WAITING_APPROVAL.value == "waiting_approval"


def test_planning_feature_flag_is_an_operational_fallback() -> None:
    settings = Settings(
        _env_file=None,
        planning_enabled=False,
        llm_provider="hosted-provider-is-ignored",
        llm_base_url="https://example.com",
    )

    runtime = create_repository_runtime(settings)

    assert runtime.llm_provider.model == "planning-disabled"
