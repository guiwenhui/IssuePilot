from pathlib import Path
from uuid import UUID

from app.services.git_client import GitClient
from app.services.workspace import UnsafeWorkspacePathError


class ImplementationWorkspace:
    def __init__(self, root: Path, git_client: GitClient) -> None:
        self.root = root.expanduser().resolve()
        self._git = git_client

    def path(self, task_id: UUID, run_id: UUID) -> Path:
        return (
            self.root
            / "tasks"
            / str(task_id)
            / "implementations"
            / str(run_id)
        ).resolve()

    async def prepare(
        self,
        source: Path,
        task_id: UUID,
        run_id: UUID,
        commit_sha: str,
    ) -> Path:
        destination = self.path(task_id, run_id)
        self._require_contained(destination)
        if destination.exists():
            if await self._git.head_sha(destination) != commit_sha:
                raise UnsafeWorkspacePathError(
                    "implementation worktree commit does not match"
                )
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        await self._git.add_worktree(source, destination, commit_sha)
        if await self._git.head_sha(destination) != commit_sha:
            raise UnsafeWorkspacePathError(
                "implementation worktree commit does not match"
            )
        return destination

    def relative_path(self, path: Path) -> str:
        self._require_contained(path)
        return path.resolve().relative_to(self.root).as_posix()

    def resolve_relative(self, value: str) -> Path:
        path = (self.root / value).resolve()
        self._require_contained(path)
        return path

    def resolve_for(self, task_id: UUID, run_id: UUID, value: str) -> Path:
        resolved = self.resolve_relative(value)
        if resolved != self.path(task_id, run_id):
            raise UnsafeWorkspacePathError(
                "implementation path does not belong to this run"
            )
        return resolved

    def _require_contained(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.root)
        except ValueError as error:
            raise UnsafeWorkspacePathError(
                "implementation path is outside workspace root"
            ) from error
