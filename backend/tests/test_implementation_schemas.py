from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.implementation import (
    FileReplacementDraft,
    ImplementationCreate,
    PatchDraft,
    TestRunCreate as RunRequest,
)


def test_file_replacement_requires_sha_and_relative_python_path() -> None:
    replacement = FileReplacementDraft(
        path="src/example.py",
        original_sha256="a" * 64,
        content="value = 1\n",
    )

    assert replacement.path == "src/example.py"

    for path in ("../secret.py", "/tmp/file.py", ".git/config", "README.md"):
        with pytest.raises(ValidationError):
            FileReplacementDraft(
                path=path,
                original_sha256="a" * 64,
                content="safe = True\n",
            )


def test_patch_draft_rejects_duplicate_paths() -> None:
    item = {
        "path": "src/example.py",
        "original_sha256": "a" * 64,
        "content": "value = 1\n",
    }

    with pytest.raises(ValidationError):
        PatchDraft(replacements=[item, item])


def test_implementation_and_test_requests_are_strict() -> None:
    implementation = ImplementationCreate(
        expected_plan_version=1,
        idempotency_key=uuid4(),
    )
    test_run = RunRequest(
        expected_patch_sha256="b" * 64,
        idempotency_key=uuid4(),
    )

    assert implementation.expected_plan_version == 1
    assert test_run.expected_patch_sha256 == "b" * 64
    with pytest.raises(ValidationError):
        ImplementationCreate.model_validate(
            {
                "expected_plan_version": 1,
                "idempotency_key": str(uuid4()),
                "command": "rm -rf /",
            }
        )
