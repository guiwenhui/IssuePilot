import pytest
from pydantic import ValidationError

from datetime import datetime, timezone
from uuid import uuid4

from app.models.task import Task
from app.schemas.task import TaskCreate, TaskResponse, TaskStatus


def test_task_create_accepts_https_repository_and_trims_issue() -> None:
    payload = TaskCreate(
        repository_url="https://github.com/example/project.git",
        issue="  Fix the parser.  ",
    )

    assert payload.repository_url == "https://github.com/example/project.git"
    assert payload.issue == "Fix the parser."


@pytest.mark.parametrize(
    "repository_url",
    [
        "http://github.com/example/project.git",
        "ssh://git@github.com/example/project.git",
        "https:///missing-host.git",
        "https://user:password@github.com/example/project.git",
    ],
)
def test_task_create_rejects_unsupported_repository_urls(
    repository_url: str,
) -> None:
    with pytest.raises(ValidationError):
        TaskCreate(repository_url=repository_url, issue="Fix the parser")


def test_task_create_rejects_blank_issue() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(
            repository_url="https://github.com/example/project.git",
            issue="   ",
        )


def test_task_create_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(
            repository_url="https://github.com/example/project.git",
            issue="Fix the parser",
            unexpected="value",
        )


def test_task_create_canonicalizes_repository_url() -> None:
    payload = TaskCreate(
        repository_url="https://github.com/pallets/markupsafe",
        issue="Fix the parser",
    )

    assert payload.repository_url == "https://github.com/pallets/markupsafe.git"


def test_task_response_exposes_persisted_clone_failure() -> None:
    now = datetime.now(timezone.utc)
    task = Task(
        id=uuid4(),
        repository_url="https://github.com/pallets/markupsafe.git",
        issue_text="Fix the parser",
        status=TaskStatus.FAILED,
        failure_code="REPOSITORY_UNAVAILABLE",
        failure_message="仓库不可用",
        created_at=now,
        updated_at=now,
    )

    response = TaskResponse.model_validate(task)

    assert response.status == TaskStatus.FAILED
    assert response.failure is not None
    assert response.failure.code == "REPOSITORY_UNAVAILABLE"


def test_task_status_includes_m6_approval_states() -> None:
    assert TaskStatus.DECISION_PENDING == "decision_pending"
    assert TaskStatus.REVISING == "revising"
    assert TaskStatus.APPROVED == "approved"
    assert TaskStatus.REJECTED == "rejected"
    assert TaskStatus.RECOVERY_BLOCKED == "recovery_blocked"
