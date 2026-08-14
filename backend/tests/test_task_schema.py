import pytest
from pydantic import ValidationError

from app.schemas.task import TaskCreate


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
