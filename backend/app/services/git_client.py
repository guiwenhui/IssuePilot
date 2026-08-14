import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Literal, Optional


SAFE_GIT_ENVIRONMENT = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_LFS_SKIP_SMUDGE": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
GIT_PREFIX = [
    "git",
    "-c",
    "credential.helper=",
    "-c",
    "http.followRedirects=false",
]


class GitClientError(Exception):
    pass


class GitUnavailableError(GitClientError):
    pass


class RepositoryUnavailableError(GitClientError):
    pass


class CloneTimeoutError(GitClientError):
    pass


class CloneFailedError(GitClientError):
    pass


@dataclass(frozen=True)
class GitCommandResult:
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TrackedEntry:
    path: str
    kind: Literal["file", "symlink", "submodule"]
    size_bytes: Optional[int]


GitRunner = Callable[
    [List[str], Optional[Path], Dict[str, str], int],
    Awaitable[GitCommandResult],
]


class GitClient:
    def __init__(
        self, timeout_seconds: int, runner: Optional[GitRunner] = None
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._runner = runner or run_git_command

    async def ensure_remote_available(self, url: str) -> None:
        result = await self._run(["ls-remote", "--symref", url, "HEAD"])
        if result.return_code != 0 or not result.stdout.strip():
            raise RepositoryUnavailableError("repository is unavailable")

    async def clone(self, url: str, destination: Path) -> None:
        result = await self._run(
            [
                "clone",
                "--depth=1",
                "--single-branch",
                "--no-tags",
                "--no-recurse-submodules",
                "--",
                url,
                str(destination),
            ]
        )
        if result.return_code != 0:
            raise CloneFailedError("repository clone failed")

    async def head_sha(self, repository: Path) -> str:
        result = await self._run(["rev-parse", "HEAD"], cwd=repository)
        sha = result.stdout.strip()
        if result.return_code != 0 or len(sha) != 40:
            raise CloneFailedError("repository HEAD is unavailable")
        return sha

    async def tracked_entries(self, repository: Path) -> List[TrackedEntry]:
        result = await self._run(
            ["ls-tree", "-r", "-l", "-z", "HEAD"], cwd=repository
        )
        if result.return_code != 0:
            raise CloneFailedError("repository tree is unavailable")
        return parse_tree_output(result.stdout)

    async def is_clean(self, repository: Path) -> bool:
        result = await self._run(
            ["status", "--porcelain", "--untracked-files=all"], cwd=repository
        )
        return result.return_code == 0 and not result.stdout

    async def _run(
        self, arguments: List[str], cwd: Optional[Path] = None
    ) -> GitCommandResult:
        try:
            return await self._runner(
                GIT_PREFIX + arguments,
                cwd,
                SAFE_GIT_ENVIRONMENT.copy(),
                self._timeout_seconds,
            )
        except FileNotFoundError as error:
            raise GitUnavailableError("git executable is unavailable") from error
        except asyncio.TimeoutError as error:
            raise CloneTimeoutError("git operation timed out") from error


async def run_git_command(
    arguments: List[str],
    cwd: Optional[Path],
    environment: Dict[str, str],
    timeout_seconds: int,
) -> GitCommandResult:
    process_environment = os.environ.copy()
    process_environment.update(environment)
    process = await asyncio.create_subprocess_exec(
        *arguments,
        cwd=cwd,
        env=process_environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise
    return GitCommandResult(
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


def parse_tree_output(output: str) -> List[TrackedEntry]:
    entries = []
    for record in output.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", maxsplit=1)
        mode, object_type, _, size = metadata.split(maxsplit=3)
        entries.append(
            TrackedEntry(
                path=path,
                kind=_entry_kind(mode, object_type),
                size_bytes=None if size == "-" else int(size),
            )
        )
    return entries


def _entry_kind(
    mode: str, object_type: str
) -> Literal["file", "symlink", "submodule"]:
    if mode == "120000":
        return "symlink"
    if mode == "160000" or object_type == "commit":
        return "submodule"
    return "file"
