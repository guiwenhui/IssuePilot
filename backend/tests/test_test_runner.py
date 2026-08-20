from pathlib import Path
import hashlib
import sys
from uuid import uuid4

import pytest

from app.services.test_runner import (
    CommandResult,
    DockerTestRunner,
    TestRunnerUnavailableError as RunnerUnavailable,
    run_command,
)


@pytest.mark.asyncio
async def test_docker_runner_uses_fixed_security_arguments(tmp_path: Path) -> None:
    calls = []

    async def runner(arguments: list[str], timeout: int) -> CommandResult:
        calls.append((arguments, timeout))
        if arguments[:3] == ["docker", "image", "inspect"]:
            return CommandResult(0, b"sha256:fixed\n", b"")
        return CommandResult(0, b"1 passed\n", b"")

    result = await DockerTestRunner("runner:m7", 120, 100, runner).run(
        tmp_path, uuid4()
    )

    arguments = calls[1][0]
    assert ["--network", "none"] == arguments[arguments.index("--network") :][:2]
    assert "--read-only" in arguments
    assert ["--cap-drop", "ALL"] == arguments[arguments.index("--cap-drop") :][:2]
    assert "no-new-privileges" in arguments
    assert "ISSUEPILOT_HARD_TIMEOUT_SECONDS=130" in arguments
    assert "sha256:fixed" in arguments
    assert arguments[-4:] == ["sha256:fixed", "-q", "-p", "no:cacheprovider"]
    assert result.exit_code == 0
    assert result.command_argv == [
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    ]


@pytest.mark.asyncio
async def test_docker_runner_truncates_output_and_hashes_full_stream(
    tmp_path: Path,
) -> None:
    async def runner(arguments: list[str], timeout: int) -> CommandResult:
        if arguments[:3] == ["docker", "image", "inspect"]:
            return CommandResult(0, b"sha256:fixed", b"")
        return CommandResult(1, b"abcdef", b"ghijkl")

    result = await DockerTestRunner("runner:m7", 120, 3, runner).run(
        tmp_path, uuid4()
    )

    assert result.stdout == "abc"
    assert result.stderr == "ghi"
    assert result.output_truncated is True
    assert result.exit_code == 1
    assert result.output_sha256 == hashlib.sha256(
        b"abcdef\0ghijkl"
    ).hexdigest()


@pytest.mark.asyncio
async def test_docker_runner_does_not_fallback_when_image_missing(
    tmp_path: Path,
) -> None:
    async def runner(arguments: list[str], timeout: int) -> CommandResult:
        return CommandResult(1, b"", b"missing")

    with pytest.raises(RunnerUnavailable):
        await DockerTestRunner("runner:m7", 120, 100, runner).run(
            tmp_path, uuid4()
        )


@pytest.mark.asyncio
async def test_docker_runner_rejects_remote_docker_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example:2375")

    with pytest.raises(RunnerUnavailable):
        await DockerTestRunner("runner:m7", 120, 100).run(
            tmp_path, uuid4()
        )


@pytest.mark.asyncio
async def test_real_command_runner_stops_at_output_limit() -> None:
    result = await run_command(
        [sys.executable, "-c", "print('x' * 1000000)"],
        timeout_seconds=5,
        output_limit=1_024,
    )

    assert len(result.stdout) == 1_024
    assert result.stdout_truncated is True
    assert result.return_code != 0
    assert len(result.output_sha256 or "") == 64
