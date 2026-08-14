from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class RepositoryTreeEntry(BaseModel):
    path: str
    kind: Literal["file", "symlink", "submodule"]
    size_bytes: Optional[int] = None


class RepositoryTreeResponse(BaseModel):
    task_id: UUID
    canonical_url: str
    commit_sha: str
    file_count: int
    total_bytes: int
    truncated: bool
    cloned_at: datetime
    entries: List[RepositoryTreeEntry]
