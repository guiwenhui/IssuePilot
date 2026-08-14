from pathlib import Path
from typing import Dict, List, Optional

import pytest

from app.services.git_client import (
    GitClient,
    GitCommandResult,
    GitUnavailableError,
    RepositoryUnavailableError,
    parse_tree_output,
)


class RecordingRunner:
    def __init__(self, result: GitCommandResult) -> None:
        self.result = result
        self.calls: List[Dict[str, object]] = []

    async def __call__(
        self,
        arguments: List[str],
        cwd: Optional[Path],
        environment: Dict[str, str],
        timeout_seconds: int,
    ) -> GitCommandResult:
        self.calls.append(
            {
                "arguments": arguments,
                "cwd": cwd,
                "environment": environment,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.result


@pytest.mark.asyncio
async def test_remote_check_uses_fixed_noninteractive_git_arguments() -> None:
    runner = RecordingRunner(GitCommandResult(0, "ref", ""))
    client = GitClient(timeout_seconds=17, runner=runner)

    await client.ensure_remote_available(
        "https://github.com/pallets/markupsafe.git"
    )

    call = runner.calls[0]
    assert call["arguments"] == [
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "http.followRedirects=false",
        "ls-remote",
        "--symref",
        "https://github.com/pallets/markupsafe.git",
        "HEAD",
    ]
    assert call["environment"] == {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    assert call["timeout_seconds"] == 17


@pytest.mark.asyncio
async def test_clone_is_shallow_and_does_not_initialize_submodules(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner(GitCommandResult(0, "", ""))
    client = GitClient(timeout_seconds=60, runner=runner)
    destination = tmp_path / "repository"

    await client.clone("https://github.com/pallets/markupsafe.git", destination)

    assert runner.calls[0]["arguments"][-8:] == [
        "clone",
        "--depth=1",
        "--single-branch",
        "--no-tags",
        "--no-recurse-submodules",
        "--",
        "https://github.com/pallets/markupsafe.git",
        str(destination),
    ]


@pytest.mark.asyncio
async def test_remote_failure_returns_safe_domain_error() -> None:
    runner = RecordingRunner(
        GitCommandResult(128, "", "fatal: secret token should not escape")
    )
    client = GitClient(timeout_seconds=60, runner=runner)

    with pytest.raises(RepositoryUnavailableError) as captured:
        await client.ensure_remote_available(
            "https://github.com/pallets/private.git"
        )

    assert "secret" not in str(captured.value)


@pytest.mark.asyncio
async def test_missing_git_maps_to_git_unavailable() -> None:
    async def missing_runner(*args: object, **kwargs: object) -> GitCommandResult:
        raise FileNotFoundError("git")

    client = GitClient(timeout_seconds=60, runner=missing_runner)

    with pytest.raises(GitUnavailableError):
        await client.ensure_remote_available(
            "https://github.com/pallets/markupsafe.git"
        )


def test_parse_tree_output_classifies_files_symlinks_and_submodules() -> None:
    output = (
        "100644 blob aaaa 12\tREADME.md\0"
        "120000 blob bbbb 9\tcurrent-link\0"
        "160000 commit cccc -\tvendor/library\0"
    )

    entries = parse_tree_output(output)

    assert [(entry.path, entry.kind, entry.size_bytes) for entry in entries] == [
        ("README.md", "file", 12),
        ("current-link", "symlink", 9),
        ("vendor/library", "submodule", None),
    ]
