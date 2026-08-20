import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from uuid import UUID


TEST_COMMAND = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
DOCKER_INFRASTRUCTURE_EXIT_CODES = {125, 126, 127}


class TestRunnerUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    output_sha256: Optional[str] = None


@dataclass(frozen=True)
class TestExecutionResult:
    command_argv: List[str]
    runner_image: str
    exit_code: Optional[int]
    timed_out: bool
    duration_ms: int
    stdout: str
    stderr: str
    output_sha256: str
    output_truncated: bool


CommandRunner = Callable[[List[str], int], Awaitable[CommandResult]]


class DockerTestRunner:
    def __init__(
        self,
        image: str,
        timeout_seconds: int,
        max_output_bytes: int,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        if timeout_seconds < 1 or max_output_bytes < 1:
            raise ValueError("test runner limits must be positive")
        if not image.strip():
            raise ValueError("test runner image must not be empty")
        self.image = image
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        self._runner = runner

    async def run(self, worktree: Path, run_id: UUID) -> TestExecutionResult:
        image_id = await self._resolve_image()
        container_name = f"issuepilot-test-{run_id}"
        arguments = _docker_arguments(
            image_id,
            worktree.resolve(),
            container_name,
            self._timeout + 10,
        )
        started = time.monotonic()
        try:
            result = await self._execute(
                arguments, self._timeout, self._max_output
            )
            if self._runner is None and (
                result.stdout_truncated or result.stderr_truncated
            ):
                await _remove_container(container_name)
            if result.return_code in DOCKER_INFRASTRUCTURE_EXIT_CODES:
                await _remove_container(container_name)
                raise TestRunnerUnavailableError(
                    "pytest runner container could not start"
                )
            timed_out = False
            exit_code: Optional[int] = result.return_code
        except asyncio.TimeoutError:
            await _remove_container(container_name)
            result = CommandResult(-1, b"", b"test execution timed out")
            timed_out = True
            exit_code = None
        elapsed = int((time.monotonic() - started) * 1000)
        return _execution_result(
            result,
            image_id,
            exit_code,
            timed_out,
            elapsed,
            self._max_output,
        )

    async def cleanup(self, run_id: UUID) -> None:
        await _remove_container(f"issuepilot-test-{run_id}")

    async def _resolve_image(self) -> str:
        try:
            result = await self._execute(
                ["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
                10,
                4_096,
            )
        except (OSError, asyncio.TimeoutError) as error:
            raise TestRunnerUnavailableError(
                "pytest runner image unavailable"
            ) from error
        image_id = result.stdout.decode("utf-8", errors="replace").strip()
        if result.return_code != 0 or not image_id.startswith("sha256:"):
            raise TestRunnerUnavailableError("pytest runner image unavailable")
        return image_id

    async def _execute(
        self, arguments: List[str], timeout_seconds: int, output_limit: int
    ) -> CommandResult:
        if self._runner is not None:
            return await self._runner(arguments, timeout_seconds)
        _require_local_docker_host()
        return await run_command(arguments, timeout_seconds, output_limit)


def _docker_arguments(
    image: str, worktree: Path, name: str, hard_timeout_seconds: int
) -> List[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        "1",
        "--memory",
        "512m",
        "--pids-limit",
        "64",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        f"ISSUEPILOT_HARD_TIMEOUT_SECONDS={hard_timeout_seconds}",
        "--mount",
        f"type=bind,src={worktree},dst=/workspace,readonly",
        "--workdir",
        "/workspace",
        image,
        "-q",
        "-p",
        "no:cacheprovider",
    ]


def _execution_result(
    result: CommandResult,
    image: str,
    exit_code: Optional[int],
    timed_out: bool,
    duration_ms: int,
    limit: int,
) -> TestExecutionResult:
    stdout, stdout_truncated = _limited_text(result.stdout, limit)
    stderr, stderr_truncated = _limited_text(result.stderr, limit)
    return TestExecutionResult(
        command_argv=TEST_COMMAND.copy(),
        runner_image=image,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        output_sha256=result.output_sha256 or _direct_output_hash(result),
        output_truncated=(
            stdout_truncated
            or stderr_truncated
            or result.stdout_truncated
            or result.stderr_truncated
        ),
    )


def _limited_text(value: bytes, limit: int) -> tuple[str, bool]:
    truncated = len(value) > limit
    return value[:limit].decode("utf-8", errors="replace"), truncated


async def run_command(
    arguments: List[str], timeout_seconds: int, output_limit: int = 1_048_576
) -> CommandResult:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "DOCKER_HOST": os.environ.get("DOCKER_HOST", ""),
    }
    process = await asyncio.create_subprocess_exec(
        *arguments,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    overflow = asyncio.Event()
    stdout_task = asyncio.create_task(
        _read_bounded(process.stdout, output_limit, overflow)
    )
    stderr_task = asyncio.create_task(
        _read_bounded(process.stderr, output_limit, overflow)
    )
    process_task = asyncio.create_task(process.wait())
    overflow_task = asyncio.create_task(overflow.wait())
    try:
        await _wait_for_process(process, process_task, overflow_task, timeout_seconds)
        stdout_result, stderr_result = await asyncio.gather(
            stdout_task, stderr_task
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task)
        raise
    finally:
        overflow_task.cancel()
    stdout, stdout_sha256 = stdout_result
    stderr, stderr_sha256 = stderr_result
    return CommandResult(
        process.returncode,
        stdout,
        stderr,
        stdout_truncated=overflow.is_set() and len(stdout) >= output_limit,
        stderr_truncated=overflow.is_set() and len(stderr) >= output_limit,
        output_sha256=_stream_output_hash(stdout_sha256, stderr_sha256),
    )


async def _wait_for_process(
    process: asyncio.subprocess.Process,
    process_task: asyncio.Task[int],
    overflow_task: asyncio.Task[bool],
    timeout_seconds: int,
) -> None:
    done, _ = await asyncio.wait(
        {process_task, overflow_task},
        timeout=timeout_seconds,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if not done:
        raise asyncio.TimeoutError
    if (
        overflow_task in done
        and overflow_task.result()
        and process.returncode is None
    ):
        process.kill()
    await process_task


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
    overflow: asyncio.Event,
) -> tuple[bytes, str]:
    if stream is None:
        return b"", hashlib.sha256(b"").hexdigest()
    captured = bytearray()
    digest = hashlib.sha256()
    while chunk := await stream.read(65_536):
        digest.update(chunk)
        remaining = limit - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > remaining:
            overflow.set()
    return bytes(captured), digest.hexdigest()


def _direct_output_hash(result: CommandResult) -> str:
    return hashlib.sha256(result.stdout + b"\0" + result.stderr).hexdigest()


def _stream_output_hash(stdout_sha256: str, stderr_sha256: str) -> str:
    manifest = f"stdout:{stdout_sha256}\0stderr:{stderr_sha256}".encode()
    return hashlib.sha256(manifest).hexdigest()


async def _remove_container(name: str) -> None:
    _require_local_docker_host()
    try:
        removed = await run_command(
            ["docker", "rm", "-f", name], 10, 4_096
        )
        missing = b"No such container" in removed.stderr
        if removed.return_code != 0 and not missing:
            raise TestRunnerUnavailableError("pytest container cleanup failed")
        inspected = await run_command(
            ["docker", "container", "inspect", name], 10, 4_096
        )
    except (OSError, asyncio.TimeoutError) as error:
        raise TestRunnerUnavailableError(
            "pytest container cleanup could not be confirmed"
        ) from error
    if inspected.return_code == 0:
        raise TestRunnerUnavailableError("pytest container is still running")
    if b"No such container" not in inspected.stderr:
        raise TestRunnerUnavailableError(
            "pytest container cleanup could not be confirmed"
        )


def _require_local_docker_host() -> None:
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host and not docker_host.startswith("unix://"):
        raise TestRunnerUnavailableError(
            "Docker must use a local Unix socket"
        )
        return
