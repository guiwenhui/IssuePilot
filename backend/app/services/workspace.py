import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Sequence
from uuid import UUID

from app.services.git_client import TrackedEntry


class WorkspaceError(Exception):
    pass


class RepositoryTooLargeError(WorkspaceError):
    pass


class RepositoryTreeLimitError(WorkspaceError):
    pass


class UnsafeWorkspacePathError(WorkspaceError):
    pass


@dataclass(frozen=True)
class WorkspaceLimits:
    max_workspace_bytes: int
    max_tracked_files: int
    max_tree_entries: int
    max_tree_depth: int


@dataclass(frozen=True)
class RepositoryManifest:
    file_count: int
    total_bytes: int
    truncated: bool
    entries: List[Dict[str, Any]]


class WorkspaceManager:
    def __init__(self, root: Path, limits: WorkspaceLimits) -> None:
        self.root = root.expanduser().resolve()
        self.staging_root = self.root / "staging"
        self.tasks_root = self.root / "tasks"
        self._limits = limits
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.tasks_root.mkdir(parents=True, exist_ok=True)

    def create_staging(self, task_id: UUID) -> Path:
        path = tempfile.mkdtemp(prefix=f"{task_id}-", dir=self.staging_root)
        return Path(path).resolve()

    def repository_path(self, task_id: UUID) -> Path:
        return (self.tasks_root / str(task_id) / "repository").resolve()

    def finalize(self, task_id: UUID, staging: Path) -> Path:
        self._require_direct_child(staging, self.staging_root)
        destination = self.repository_path(task_id)
        if destination.exists():
            raise UnsafeWorkspacePathError("task workspace already exists")
        destination.parent.mkdir(parents=True, exist_ok=False)
        os.replace(staging, destination)
        return destination

    def cleanup_staging(self, staging: Path) -> None:
        self._require_direct_child(staging, self.staging_root)
        if staging.exists():
            shutil.rmtree(staging)

    def build_manifest(
        self, repository: Path, tracked_entries: Sequence[TrackedEntry]
    ) -> RepositoryManifest:
        workspace_bytes = _regular_file_bytes(repository)
        if workspace_bytes > self._limits.max_workspace_bytes:
            raise RepositoryTooLargeError("repository workspace is too large")
        self._validate_tree(tracked_entries)
        visible_entries = sorted(tracked_entries, key=lambda entry: entry.path)[
            : self._limits.max_tree_entries
        ]
        return RepositoryManifest(
            file_count=len(tracked_entries),
            total_bytes=sum(entry.size_bytes or 0 for entry in tracked_entries),
            truncated=len(tracked_entries) > len(visible_entries),
            entries=[_entry_dict(entry) for entry in visible_entries],
        )

    def _validate_tree(self, entries: Sequence[TrackedEntry]) -> None:
        if len(entries) > self._limits.max_tracked_files:
            raise RepositoryTreeLimitError("repository has too many files")
        for entry in entries:
            parts = PurePosixPath(entry.path).parts
            if (
                not parts
                or PurePosixPath(entry.path).is_absolute()
                or any(part in {"", ".", ".."} for part in parts)
                or parts[0] == ".git"
                or len(parts) > self._limits.max_tree_depth
            ):
                raise RepositoryTreeLimitError("repository path is unsafe or too deep")

    @staticmethod
    def _require_direct_child(path: Path, parent: Path) -> None:
        resolved = path.resolve()
        if resolved.parent != parent.resolve():
            raise UnsafeWorkspacePathError("workspace path is outside staging root")


def _regular_file_bytes(root: Path) -> int:
    total = 0
    for current_root, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not (Path(current_root) / name).is_symlink()
        ]
        for name in files:
            path = Path(current_root) / name
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    return total


def _entry_dict(entry: TrackedEntry) -> Dict[str, Any]:
    return {
        "path": entry.path,
        "kind": entry.kind,
        "size_bytes": entry.size_bytes,
    }
