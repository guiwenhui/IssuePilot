from dataclasses import dataclass
from typing import Any, Dict, List, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from app.llms.base import ChatModelProvider
from app.schemas.implementation import PatchDraft


class ImplementationState(TypedDict, total=False):
    implementation_run_id: str
    issue: str
    commit_sha: str
    plan: Dict[str, Any]
    files: List[Dict[str, Any]]
    patch_draft: Dict[str, Any]
    patch_sha256: str
    test_request: Dict[str, Any]


class ImplementationSourceFile(BaseModel):
    path: str
    sha256: str = Field(min_length=64, max_length=64)
    content: str

    model_config = ConfigDict(extra="forbid")


class ImplementationBundle(BaseModel):
    implementation_run_id: UUID
    issue: str
    commit_sha: str = Field(min_length=40, max_length=40)
    plan: Dict[str, Any]
    files: List[ImplementationSourceFile] = Field(min_length=1, max_length=4)

    model_config = ConfigDict(extra="forbid")


class ImplementationGraphAdapter(Protocol):
    async def load_bundle(self, run_id: UUID) -> ImplementationBundle:
        ...

    async def apply_patch(self, run_id: UUID, draft: PatchDraft) -> str:
        ...

    async def run_test(self, test_run_id: UUID) -> None:
        ...


@dataclass(frozen=True)
class ImplementationRuntimeContext:
    adapter: ImplementationGraphAdapter
    provider: ChatModelProvider
