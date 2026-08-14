from datetime import datetime
from enum import Enum
from typing import Any, Dict, List
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskStatus(str, Enum):
    CREATED = "created"


class TaskCreate(BaseModel):
    repository_url: str = Field(min_length=1, max_length=2048)
    issue: str = Field(min_length=1, max_length=20_000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("repository_url", mode="before")
    @classmethod
    def validate_repository_url(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("repository_url must be a string")

        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("repository_url must be an HTTPS URL with a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("repository_url must not include credentials")
        return normalized

    @field_validator("issue", mode="before")
    @classmethod
    def normalize_issue(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("issue must be a string")
        return value.strip()


class TaskResponse(BaseModel):
    task_id: UUID = Field(validation_alias="id")
    repository_url: str
    issue: str = Field(validation_alias="issue_text")
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: List[Dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
