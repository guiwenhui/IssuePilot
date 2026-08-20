import hashlib
import stat
import subprocess
from pathlib import Path

import pytest

from app.schemas.implementation import FileReplacementDraft
from app.services.git_client import GitClient
from app.services.implementation_workspace import ImplementationWorkspace
from app.services.patch_service import (
    PatchLimits,
    PatchService,
    PatchSourceChangedError,
    PatchValidationError,
)
from app.services.workspace import UnsafeWorkspacePathError


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "IssuePilot Test")
    (path / "example.py").write_text("value = 1\n")
    (path / "other.py").write_text("other = 1\n")
    _git(path, "add", "example.py", "other.py")
    _git(path, "commit", "-m", "fixture")
    return path


@pytest.mark.asyncio
async def test_worktree_patch_preserves_source_repository(tmp_path: Path) -> None:
    source = _repository(tmp_path / "source")
    commit_sha = _git(source, "rev-parse", "HEAD")
    client = GitClient(10)
    workspace = ImplementationWorkspace(tmp_path / "managed", client)
    task_id = __import__("uuid").uuid4()
    run_id = __import__("uuid").uuid4()
    worktree = await workspace.prepare(source, task_id, run_id, commit_sha)
    original = (worktree / "example.py").read_bytes()
    original_mode = stat.S_IMODE((worktree / "example.py").stat().st_mode)
    replacement = FileReplacementDraft(
        path="example.py",
        original_sha256=hashlib.sha256(original).hexdigest(),
        content="value = 2\n",
    )

    artifact = await PatchService(client, PatchLimits()).apply(
        worktree, {"example.py"}, [replacement]
    )

    assert "-value = 1" in artifact.unified_diff
    assert "+value = 2" in artifact.unified_diff
    assert artifact.file_count == 1
    assert (source / "example.py").read_text() == "value = 1\n"
    assert stat.S_IMODE((worktree / "example.py").stat().st_mode) == original_mode
    assert await client.is_clean(source)


@pytest.mark.asyncio
async def test_patch_rejects_unapproved_and_stale_file(tmp_path: Path) -> None:
    source = _repository(tmp_path / "source")
    commit_sha = _git(source, "rev-parse", "HEAD")
    client = GitClient(10)
    workspace = ImplementationWorkspace(tmp_path / "managed", client)
    worktree = await workspace.prepare(
        source,
        __import__("uuid").uuid4(),
        __import__("uuid").uuid4(),
        commit_sha,
    )
    service = PatchService(client, PatchLimits())

    with pytest.raises(PatchValidationError):
        await service.apply(
            worktree,
            {"example.py"},
            [
                FileReplacementDraft(
                    path="other.py",
                    original_sha256="a" * 64,
                    content="other = 2\n",
                )
            ],
        )
    with pytest.raises(PatchSourceChangedError):
        await service.apply(
            worktree,
            {"example.py"},
            [
                FileReplacementDraft(
                    path="example.py",
                    original_sha256="a" * 64,
                    content="value = 2\n",
                )
            ],
        )


@pytest.mark.asyncio
async def test_patch_inspection_rejects_untracked_worktree_state(
    tmp_path: Path,
) -> None:
    source = _repository(tmp_path / "source")
    client = GitClient(10)
    worktree = await ImplementationWorkspace(tmp_path / "managed", client).prepare(
        source,
        __import__("uuid").uuid4(),
        __import__("uuid").uuid4(),
        _git(source, "rev-parse", "HEAD"),
    )
    (worktree / "rogue.py").write_text("unapproved = True\n")

    with pytest.raises(PatchSourceChangedError):
        await PatchService(client, PatchLimits()).inspect(
            worktree, {"example.py"}
        )


def test_implementation_workspace_rejects_another_runs_relative_path(
    tmp_path: Path,
) -> None:
    workspace = ImplementationWorkspace(tmp_path / "managed", GitClient(10))
    task_id = __import__("uuid").uuid4()
    run_id = __import__("uuid").uuid4()
    other_run = __import__("uuid").uuid4()
    wrong = workspace.path(task_id, other_run)

    with pytest.raises(UnsafeWorkspacePathError):
        workspace.resolve_for(
            task_id, run_id, workspace.relative_path(wrong)
        )
