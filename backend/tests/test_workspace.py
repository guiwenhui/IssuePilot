from pathlib import Path
from uuid import uuid4

import pytest

from app.services.git_client import TrackedEntry
from app.services.workspace import (
    RepositoryTooLargeError,
    RepositoryTreeLimitError,
    UnsafeWorkspacePathError,
    WorkspaceLimits,
    WorkspaceManager,
)


def make_manager(tmp_path: Path, **overrides: int) -> WorkspaceManager:
    values = {
        "max_workspace_bytes": 100,
        "max_tracked_files": 3,
        "max_tree_entries": 2,
        "max_tree_depth": 3,
    }
    values.update(overrides)
    return WorkspaceManager(tmp_path / "workspaces", WorkspaceLimits(**values))


def test_workspace_paths_are_derived_from_task_uuid(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    task_id = uuid4()

    staging = manager.create_staging(task_id)

    assert staging.parent == manager.staging_root
    assert str(task_id) in staging.name
    assert manager.repository_path(task_id).is_relative_to(manager.root)


def test_manifest_enforces_file_count_and_depth(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()

    with pytest.raises(RepositoryTreeLimitError):
        manager.build_manifest(
            repository,
            [TrackedEntry(f"file-{index}.py", "file", 1) for index in range(4)],
        )

    with pytest.raises(RepositoryTreeLimitError):
        manager.build_manifest(
            repository,
            [TrackedEntry("one/two/three/four.py", "file", 1)],
        )


def test_manifest_reports_all_files_but_limits_response_entries(
    tmp_path: Path,
) -> None:
    manager = make_manager(tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    entries = [TrackedEntry(f"file-{index}.py", "file", 2) for index in range(3)]

    manifest = manager.build_manifest(repository, entries)

    assert manifest.file_count == 3
    assert manifest.total_bytes == 6
    assert manifest.truncated is True
    assert len(manifest.entries) == 2


def test_workspace_size_does_not_follow_external_symlink(tmp_path: Path) -> None:
    manager = make_manager(tmp_path, max_workspace_bytes=20)
    repository = tmp_path / "repository"
    repository.mkdir()
    external = tmp_path / "external.bin"
    external.write_bytes(b"x" * 200)
    (repository / "link").symlink_to(external)

    manager.build_manifest(
        repository,
        [TrackedEntry("link", "symlink", len(str(external)))],
    )


def test_workspace_rejects_oversized_checked_out_content(tmp_path: Path) -> None:
    manager = make_manager(tmp_path, max_workspace_bytes=10)
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "large.bin").write_bytes(b"x" * 11)

    with pytest.raises(RepositoryTooLargeError):
        manager.build_manifest(
            repository,
            [TrackedEntry("large.bin", "file", 11)],
        )


def test_cleanup_rejects_paths_outside_staging_root(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    with pytest.raises(UnsafeWorkspacePathError):
        manager.cleanup_staging(unrelated)
