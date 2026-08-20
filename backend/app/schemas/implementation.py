from datetime import datetime
from pathlib import PurePosixPath
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileReplacementDraft(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    original_sha256: str = Field(pattern=SHA256_PATTERN)
    content: str = Field(min_length=1, max_length=81_920)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.parts[0] == ".git"
            or path.suffix != ".py"
        ):
            raise ValueError("replacement path must be a safe Python path")
        return value


class PatchDraft(StrictModel):
    replacements: List[FileReplacementDraft] = Field(
        min_length=1, max_length=4
    )

    @model_validator(mode="after")
    def require_unique_paths(self):
        paths = [item.path for item in self.replacements]
        if len(paths) != len(set(paths)):
            raise ValueError("replacement paths must be unique")
        return self


class ImplementationCreate(StrictModel):
    expected_plan_version: int = Field(ge=1, le=5)
    idempotency_key: UUID


class TestRunCreate(StrictModel):
    expected_patch_sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: UUID


class PatchFile(StrictModel):
    path: str
    original_sha256: str
    patched_sha256: str


class PatchArtifactResponse(StrictModel):
    sha256: str
    unified_diff: str
    files: List[PatchFile]
    file_count: int
    insertions: int
    deletions: int
    created_at: datetime


class TestRunResponse(StrictModel):
    test_run_id: UUID
    status: Literal["pending", "running", "passed", "failed"]
    command_argv: List[str]
    runner_image: str
    exit_code: Optional[int]
    timed_out: bool
    duration_ms: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    output_sha256: Optional[str]
    output_truncated: bool
    created_at: datetime
    finished_at: Optional[datetime]


class ImplementationRunResponse(StrictModel):
    implementation_run_id: UUID
    task_id: UUID
    plan_id: UUID
    plan_version: int
    base_commit: str
    status: str
    provider: str
    model: str
    failure_code: Optional[str]
    failure_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class ImplementationResponse(StrictModel):
    run: ImplementationRunResponse
    patch: Optional[PatchArtifactResponse] = None
    test: Optional[TestRunResponse] = None
